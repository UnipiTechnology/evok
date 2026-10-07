import json
import logging
import traceback
from urllib.parse import urlparse

from tornado import websocket

from .devices import DI, RO, AI, AO, SENSOR
from .devices import Devices, devtype_of, num_to_devtype_name
from .handlers_base import CLIENT_ERRORS, check_params, client_error
from .log import logger

# clients notified by status_cb() in evok.py, websocket clients and the webhook
registered_ws = {}


class WsHandler(websocket.WebSocketHandler):

    def initialize(self, all_filtered=False):
        self.all_filtered = all_filtered

    def check_origin(self, origin):
        # fix issue when Node-RED removes the 'prefix://'
        parsed_origin = urlparse(origin)
        origin = parsed_origin.netloc
        origin = origin.lower()
        # return origin == host or origin_origin == host
        return True

    def open(self):
        self.filter = ["default"]
        logger.debug("New WebSocket client connected")
        if not ("all" in registered_ws):
            registered_ws["all"] = set()
        registered_ws["all"].add(self)

    def on_event(self, device):
        """ Send the states of the changed devices, always as a list

            A change of Modbus devices comes as a Proxy with a list of states,
            a change of a 1-Wire sensor as the sensor with its state.
        """
        try:
            states = device.full()
            if isinstance(states, dict):
                states = [states]
            if not self._is_default_filter():
                states = [state for state in states if devtype_of(state['dev']) in self.filter]
            if states:
                self.write_message(json.dumps(states))
        except Exception as E:
            logger.error(f"WsHandler error in event: {E}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()

    async def on_message(self, message):
        try:
            message = json.loads(message)
            if not isinstance(message, dict):
                raise ValueError("The message must be an object")
            cmd = message.get("cmd")
            # get FULL state of each IO
            if cmd == "all":
                await self.write_message(json.dumps(self._all()))
            elif cmd == "filter":
                self._set_filter(message.get("devices"))
            elif cmd in ("full", "set"):
                if "dev" not in message or "circuit" not in message:
                    raise ValueError(f"Command '{cmd}' requires 'dev' and 'circuit'")
                dev = message["dev"]
                device = Devices.by_name(dev, message["circuit"])
                if cmd == "full":
                    # full() is not a coroutine, send the state only to the requesting client
                    await self.write_message(json.dumps(device.full()))
                else:
                    await device.set(**self._set_params(dev, message))
            else:
                raise ValueError(f"Unknown command '{cmd}'")
        except CLIENT_ERRORS as E:
            errors, _ = client_error(E)
            logger.error(f"WS: {errors}")
            await self._send_error(errors)
        except Exception as E:
            logger.exception(f"WS: {str(E)}")
            await self._send_error({'Server error': 'internal'})

    async def _send_error(self, errors: dict):
        """ Errors are sent only to the requesting client, in the format of REST """
        try:
            await self.write_message(json.dumps({'success': False, 'errors': errors}))
        except websocket.WebSocketClosedError:
            pass

    def _is_default_filter(self) -> bool:
        return self.filter == ["default"]

    def _all(self) -> list:
        """ State of all devices, with all_filtered only of the devices passing the filter """
        if self.all_filtered and self._is_default_filter():
            devtypes = [DI, RO, AI, AO, SENSOR]
        elif self.all_filtered:
            devtypes = [devtype for devtype in num_to_devtype_name.values() if devtype in self.filter]
        else:
            devtypes = num_to_devtype_name.values()
        return [dev.full() for devtype in devtypes for dev in Devices.by_name(devtype)]

    def _set_filter(self, names):
        """ Device types sent in events, altnames are converted to the device types,
            unknown types are skipped, ["default"] restores the default filter
        """
        if not isinstance(names, list):
            raise ValueError("Command 'filter' requires a list in 'devices'")
        if names[:1] == ["default"]:
            self.filter = ["default"]
            return
        devtypes = [devtype_of(str(name)) for name in names]
        devtypes = [devtype for devtype in devtypes if devtype in num_to_devtype_name.values()]
        if names and not devtypes:
            raise ValueError(f"Invalid 'devices' argument: {names}")
        self.filter = devtypes

    @staticmethod
    def _set_params(dev, message) -> dict:
        """ Params of set() as in REST: other keys of the message, a dict in 'value' or 'value' itself,
            validated by the schema of the device type
        """
        kw = {key: val for (key, val) in message.items() if key not in ("circuit", "value", "cmd", "dev")}
        value = message.get("value")
        if isinstance(value, dict):
            kw.update(value)
        elif value is not None:
            kw["value"] = value
        check_params(dev, kw)
        return kw

    def on_close(self):
        if ("all" in registered_ws) and (self in registered_ws["all"]):
            registered_ws["all"].remove(self)
