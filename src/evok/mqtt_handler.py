"""The MQTT API: the states of the devices are published to a broker, the commands are received from it

Topics, with the prefix of the configuration (evok by default):

- <prefix>/status                  'online' / 'offline', retained, 'offline' is the last will
- <prefix>/<devtype>/<circuit>     full() of the device as JSON, retained, after a change and the connection
- <prefix>/<devtype>/<circuit>/set the params of set() as the body of REST, a plain value is {"value": ...}
- <prefix>/error                   the error of a command in the format of REST, not retained

With ha_discovery the devices are announced to Home Assistant (mqtt_ha), the configs of the entities
are published before the states.

The states are queued as for the WebSocket, the last state of each device is published. A command is
validated by the schema of the device type and done by set_devices(), under the lock of a Modbus unit,
the event of the changed devices follows. The access is controlled by the broker, read_only disables
the commands.
"""

import asyncio
import json
import logging
import socket

import aiomqtt

from .devices import RUN, Devices, devtype_of, num_to_devtype_name
from .handlers_base import CLIENT_ERRORS, check_params, client_error
from .modbus import set_devices
from .mqtt_ha import discovery
from .ws_handler import registered_ws

logger = logging.getLogger(__name__)

RECONNECT_DELAY = 5  # s, the next connection to the broker after a failure

# all device types with devices, the aliases (run) are not a device
DEFAULT_DEVICE_MASK = [devtype for devtype in num_to_devtype_name.values() if devtype not in (RUN, "board")]


class MqttSettings:
    """The options of apis: mqtt, ValueError if they are invalid"""

    def __init__(self, conf: dict):
        conf = dict(conf or {})
        conf.pop("enabled", None)
        self.hostname = conf.pop("hostname", "127.0.0.1")
        if not isinstance(self.hostname, str) or not self.hostname:
            raise ValueError(f"'hostname' must be a non-empty string, not '{self.hostname}'")
        self.ca_file = conf.pop("ca_file", None)
        self.cert_file = conf.pop("cert_file", None)
        self.key_file = conf.pop("key_file", None)
        self.tls = _bool(conf.pop("tls", False), "tls") or any((self.ca_file, self.cert_file, self.key_file))
        if self.key_file and not self.cert_file:
            raise ValueError("'key_file' requires 'cert_file'")
        self.port = conf.pop("port", 8883 if self.tls else 1883)
        if not isinstance(self.port, int) or isinstance(self.port, bool) or not 1 <= self.port <= 65535:
            raise ValueError(f"'port' must be an integer 1..65535, not '{self.port}'")
        self.username = conf.pop("username", None)
        self.password = conf.pop("password", None)
        for name, value in (("username", self.username), ("password", self.password)):
            if value is not None and not isinstance(value, str):
                raise ValueError(f"'{name}' must be a string")
        if self.password is not None and self.username is None:
            raise ValueError("'password' requires 'username'")
        self.client_id = conf.pop("client_id", f"evok-{socket.gethostname()}")
        self.prefix = conf.pop("prefix", "evok")
        for name, value in (("client_id", self.client_id), ("prefix", self.prefix)):
            if not isinstance(value, str) or not value:
                raise ValueError(f"'{name}' must be a non-empty string")
        if any(char in self.prefix for char in "+#") or self.prefix.startswith("/") or self.prefix.endswith("/"):
            raise ValueError(
                f"'prefix' must be a topic without the wildcards and the leading or trailing '/', not '{self.prefix}'"
            )
        self.qos = conf.pop("qos", 0)
        if self.qos not in (0, 1, 2) or isinstance(self.qos, bool):
            raise ValueError(f"'qos' must be 0, 1 or 2, not '{self.qos}'")
        self.keepalive = conf.pop("keepalive", 60)
        if not isinstance(self.keepalive, int) or isinstance(self.keepalive, bool) or self.keepalive <= 0:
            raise ValueError(f"'keepalive' must be a positive integer, not '{self.keepalive}'")
        mask = conf.pop("device_mask", DEFAULT_DEVICE_MASK)
        if not isinstance(mask, list):
            raise ValueError("'device_mask' must be a list of device types")
        self.device_mask = {devtype_of(str(name)) for name in mask}
        unknown = self.device_mask - set(DEFAULT_DEVICE_MASK)
        if unknown:
            raise ValueError(f"unknown device types in 'device_mask': {sorted(unknown)}")
        self.read_only = _bool(conf.pop("read_only", False), "read_only")
        self.ha_discovery = _bool(conf.pop("ha_discovery", False), "ha_discovery")
        self.ha_prefix = conf.pop("ha_prefix", "homeassistant")
        if (
            not isinstance(self.ha_prefix, str)
            or not self.ha_prefix
            or any(c in self.ha_prefix for c in "+#")
            or self.ha_prefix.startswith("/")
            or self.ha_prefix.endswith("/")
        ):
            raise ValueError(
                f"'ha_prefix' must be a topic without the wildcards and the leading or trailing '/', "
                f"not '{self.ha_prefix}'"
            )
        if conf:
            raise ValueError(f"unknown options {sorted(conf)}")

    def client_kwargs(self) -> dict:
        """The arguments of aiomqtt.Client"""
        tls_params = (
            aiomqtt.TLSParameters(ca_certs=self.ca_file, certfile=self.cert_file, keyfile=self.key_file)
            if self.tls
            else None
        )
        return {
            "hostname": self.hostname,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "identifier": self.client_id,
            "keepalive": self.keepalive,
            "tls_params": tls_params,
            "will": aiomqtt.Will(f"{self.prefix}/status", "offline", qos=self.qos, retain=True),
        }


def _bool(value, name) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"'{name}' must be true or false, not '{value}'")
    return value


class MqttHandler:
    """Publishes the changed devices to the broker, receives the commands"""

    def __init__(self, settings: MqttSettings, client_factory=aiomqtt.Client):
        self.settings = settings
        self.client_factory = client_factory
        self.pending: dict[tuple, dict] = {}  # the last state of each changed device not published yet
        self.announced: dict[str, dict] = {}  # the published configs of Home Assistant by their topic
        self.wakeup = asyncio.Event()
        self.client = None  # the connected client
        self.task: asyncio.Task | None = None
        self.logged_error = None  # the logged failure of the connection, not logged again

    def topic(self, devtype, circuit=None) -> str:
        return f"{self.settings.prefix}/{devtype}" + ("" if circuit is None else f"/{circuit}")

    def open(self):
        """Receive the events and connect to the broker"""
        registered_ws.setdefault("all", set()).add(self)
        if not self.settings.read_only and self.settings.username is None:
            logger.warning(
                f"MQTT: the commands are accepted from any client of the broker "
                f"{self.settings.hostname}:{self.settings.port}, set 'username' and 'password' "
                f"of a user with an ACL of the broker, or 'read_only'"
            )
        self.task = asyncio.create_task(self.run())

    def on_event(self, device):
        """Queue the states of the changed devices of device_mask

        A change of Modbus devices comes as a Proxy with a list of states,
        a change of a 1-Wire sensor as the sensor with its state.
        """
        try:
            states = device.full()
            self._queue([states] if isinstance(states, dict) else states)
        except Exception:
            logger.exception("MQTT error in event")

    def _queue(self, states):
        for state in states:
            devtype = devtype_of(state["dev"])
            if devtype in self.settings.device_mask and "circuit" in state:
                self.pending[(devtype, str(state["circuit"]))] = state
        if self.pending:
            self.wakeup.set()

    def _queue_all(self):
        """The states of all devices, published after the connection, the retained states are complete"""
        self._queue(
            [
                dev.full()
                for devtype in num_to_devtype_name.values()
                if devtype in self.settings.device_mask
                for dev in Devices.by_name(devtype)
            ]
        )

    async def run(self):
        """Connect to the broker, again after a failure"""
        address = f"{self.settings.hostname}:{self.settings.port}"
        while True:
            connected = False
            try:
                async with self.client_factory(**self.settings.client_kwargs()) as client:
                    connected = True
                    self.logged_error = None
                    logger.info(f"MQTT connected to the broker {address} as '{self.settings.client_id}'")
                    await self._connected(client)
            except aiomqtt.MqttError as E:
                if connected:
                    logger.error(
                        f"MQTT: the connection to the broker {address} was lost: {E}; "
                        f"connecting again every {RECONNECT_DELAY} s"
                    )
                elif str(E) != self.logged_error:
                    self.logged_error = str(E)
                    logger.error(
                        f"MQTT: cannot connect to the broker {address}: {E}; connecting again every "
                        f"{RECONNECT_DELAY} s, the next errors are not logged"
                    )
            finally:
                self.client = None
            await asyncio.sleep(RECONNECT_DELAY)

    async def _connected(self, client):
        self.client = client
        await client.publish(self.topic("status"), "online", qos=self.settings.qos, retain=True)
        if not self.settings.read_only:
            await client.subscribe(f"{self.settings.prefix}/+/+/set", qos=self.settings.qos)
        self.pending.clear()
        # the configs are published again after the connection, before the states
        self.announced.clear()
        self._queue_all()
        publisher = asyncio.create_task(self._publish(client))
        try:
            # a lost connection raises MqttError, also without the subscription
            async for message in client.messages:
                await self._command(client, message)
        finally:
            publisher.cancel()

    async def _publish(self, client):
        """Publish the pending states, the changes while publishing are merged"""
        while True:
            await self.wakeup.wait()
            self.wakeup.clear()
            while self.pending:
                key = next(iter(self.pending))
                state = self.pending.pop(key)
                try:
                    if self.settings.ha_discovery:
                        await self._announce(client, key, state)
                    await client.publish(self.topic(*key), json.dumps(state), qos=self.settings.qos, retain=True)
                except aiomqtt.MqttError:
                    raise
                except Exception as E:  # noqa: BLE001
                    logger.error(f"MQTT error in publishing {self.topic(*key)}: {E}")

    async def _announce(self, client, key, state):
        """Publish the configs of Home Assistant of the device, a changed config again"""
        for topic, config in discovery(
            self.settings.prefix, self.settings.ha_prefix, *key, state, read_only=self.settings.read_only
        ):
            if self.announced.get(topic) != config:
                await client.publish(topic, json.dumps(config), qos=self.settings.qos, retain=True)
                self.announced[topic] = config

    async def _command(self, client, message):
        """<prefix>/<devtype>/<circuit>/set with the params of set(), an error is published to <prefix>/error"""
        topic = str(message.topic)
        try:
            parts = topic[len(self.settings.prefix) + 1 :].split("/")
            if not topic.startswith(self.settings.prefix + "/") or len(parts) != 3 or parts[2] != "set":
                raise ValueError(f"Invalid topic {topic}")
            if self.settings.read_only:
                raise ValueError("The MQTT API is read-only")
            devtype, circuit = parts[0], parts[1]
            device = Devices.by_name(devtype, circuit)
            kw = self._params(message.payload)
            check_params(devtype, kw)
            await set_devices([(device, kw)])
        except CLIENT_ERRORS as E:
            errors, _ = client_error(E)
            await self._error(client, topic, errors)
        except Exception:
            logger.exception(f"MQTT {topic}")
            await self._error(client, topic, {"Server error": "internal"})

    @staticmethod
    def _params(payload) -> dict:
        """A JSON object is the params of set(), another value (JSON or a plain text) is the value"""
        text = payload.decode() if isinstance(payload, (bytes, bytearray)) else str(payload)
        try:
            data = json.loads(text)
        except ValueError:
            data = text.strip()
        return data if isinstance(data, dict) else {"value": data}

    async def _error(self, client, topic, errors: dict):
        logger.error(f"MQTT {topic}: {errors}")
        await client.publish(
            self.topic("error"), json.dumps({"topic": topic, "success": False, "errors": errors}), qos=self.settings.qos
        )

    async def stop(self, timeout: float = 2.0):
        """Publish the pending states and 'offline', the last will is sent only on a lost connection"""
        registered_ws.get("all", set()).discard(self)
        client = self.client
        if client is not None:
            try:
                async with asyncio.timeout(timeout):
                    for key, state in list(self.pending.items()):
                        await client.publish(self.topic(*key), json.dumps(state), qos=self.settings.qos, retain=True)
                    self.pending.clear()
                    await client.publish(self.topic("status"), "offline", qos=self.settings.qos, retain=True)
            except (aiomqtt.MqttError, TimeoutError) as E:
                logger.warning(f"MQTT: 'offline' was not published: {E}")
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
