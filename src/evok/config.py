import logging
import os

import yaml
from tenacity import AsyncRetrying, retry_never, stop_after_attempt, stop_after_delay, wait_fixed
from tmodbus import (
    AsyncRtuTransport,
    AsyncSmartTransport,
    AsyncTcpTransport,
)

from . import w1
from .devices import DEVICE_INFO, MODBUS_SLAVE, OWBUS, SERIALBUS, TCPBUS, Aliases, Devices
from .modbus import ModbusScanner
from .modbus.transport import BusTransport

logger = logging.getLogger(__name__)


class EvokConfigError(Exception):
    pass


API_SECTIONS = ("rpc", "websocket", "webhook", "mqtt")  # the sections of apis with the options of an API


class HWDict:
    def __init__(self, dir_paths: list[str] | None = None, paths: list[str] | None = None):
        """
        :param dir_paths: paths to directories with definitions, all '.yaml' files are loaded
        :param paths: paths to definition files
        """
        self.definitions: dict[str, dict] = {}
        scope = []
        if dir_paths is not None:
            for dp in dir_paths:
                if not os.path.isdir(dp):
                    logger.error(f"HWDict: Entered path is not directory: '{dp}'!")
                    continue
                scope.extend(os.path.join(dp, f) for f in sorted(os.listdir(dp)))
        if paths is not None:
            scope.extend(paths)
        if not scope:
            logger.warning("HWDict: no scope!")
        for file_path in scope:
            if not file_path.endswith(".yaml") or not os.path.isfile(file_path):
                continue
            file_name = os.path.basename(file_path)[: -len(".yaml")]
            # an invalid file is skipped, the other definitions are loaded
            try:
                with open(file_path) as yfile:
                    ydata = yaml.safe_load(yfile)
            except (OSError, yaml.YAMLError) as E:
                logger.error(f"HWDict: Cannot load definition file '{file_path}': {E}")
                continue
            if ydata is None:
                logger.warning(f"Empty Definition file '{file_path}'! skipping...")
                continue
            if not isinstance(ydata, dict):
                logger.error(f"HWDict: Definition file '{file_path}' does not contain a mapping! skipping...")
                continue
            self.definitions[file_name] = ydata
            logger.debug(f"YAML Definition loaded: {file_path}, definition count {len(self.definitions)}")


class BusDevice:
    """A Modbus bus, full() returns its configuration and its Modbus devices, it cannot be set"""

    devtype = None

    def __init__(self, circuit: str, bus_driver: AsyncSmartTransport, **settings):
        self.bus_driver = bus_driver
        self.circuit = circuit
        self.settings = settings
        self.devices: list[str] = []  # the circuits of the created Modbus devices of the bus

    def full(self):
        return dict({"dev": self.devtype, "circuit": self.circuit}, **self.settings, devices=list(self.devices))


class TcpBusDevice(BusDevice):
    """The connection is opened by the first request, see retry_strategies()"""

    devtype = TCPBUS


class SerialBusDevice(BusDevice):
    """The serial port is opened by the first request, see retry_strategies()"""

    devtype = SERIALBUS


class DeviceInfo:
    def __init__(self, name: str, family: str, model: str, sn: int | None, board_count: int):
        """
        :param family: [Neuron, Patron, UNIPI1, Iris]
        :param model: [S103, M533, ...]
        :param sn: serial number
        :param board_count: number of boards
        """
        self.family: str = family
        self.model: str = model
        self.sn: int | None = sn
        self.board_count: int = board_count
        self.circuit: str = f"{name}"

    def full(self):
        return {
            "dev": "device_info",
            "family": self.family,
            "model": self.model,
            "sn": self.sn,
            "board_count": self.board_count,
            "circuit": self.circuit,
        }


class EvokConfig:
    def __init__(self, conf_dir_path: str):
        self.conf_dir_path = conf_dir_path
        data = self.__get_final_conf([conf_dir_path + "/config.yaml"])
        self.comm_channels: dict = self.__get_comm_channels(data)
        self.apis: dict = self.__get_apis_conf(data)
        self.logging: dict = self.__get_logging_conf(data)

    def __merge_data(self, source: dict, append: dict):
        for key, value in append.items():
            if isinstance(source.get(key), dict) and isinstance(value, dict):
                source[key] = self.__merge_data(source[key], value)
            else:
                source[key] = value
        return source

    def __get_final_conf(self, scope: list[str], check_autogen: bool = True) -> dict:
        """Merge the config files in the scope, the later ones override the former ones"""
        final_conf = {}
        for path in scope:
            try:
                with open(path) as f:
                    ydata = yaml.safe_load(f)
            except FileNotFoundError:
                logger.warning(f"Config file {path} not found!")
                continue
            if ydata is None:
                logger.warning(f"Config file {path} is empty!")
                continue
            if not isinstance(ydata, dict):
                raise EvokConfigError(f"Config file {path} does not contain a mapping")
            self.__merge_data(final_conf, ydata)
        if check_autogen and final_conf.get("autogen", False):
            return self.__get_final_conf([self.conf_dir_path + "/autogen.yaml", *scope], check_autogen=False)
        return final_conf

    @staticmethod
    def __get_comm_channels(data: dict) -> dict:
        ret = {}
        if "comm_channels" not in data:
            logger.warning("Section 'comm_channels' not in configuration!")
            return ret
        for name, value in (data["comm_channels"] or {}).items():
            ret[name] = value
        return ret

    @staticmethod
    def __get_apis_conf(data: dict) -> dict:
        """The options of the APIs; an empty section of an API is {}, e.g. with all its options commented out,
        a section which is not a mapping is an error
        """
        ret = {}
        if "apis" not in data:
            logger.warning("Section 'apis' not in configuration!")
            return ret
        apis = data["apis"] or {}
        if not isinstance(apis, dict):
            raise EvokConfigError(f"apis must be a mapping of the options of the APIs, not '{apis}'")
        for name, value in apis.items():
            if name in API_SECTIONS:
                value = value or {}
                if not isinstance(value, dict):
                    raise EvokConfigError(f"apis: {name} must be a mapping of its options, not '{value}'")
            ret[name] = value
        return ret

    @staticmethod
    def __get_logging_conf(data: dict) -> dict:
        ret = {}
        if "logging" not in data:
            logger.warning("Section 'logging' not in configuration!")
            return ret
        for name, value in (data["logging"] or {}).items():
            ret[name] = value
        return ret

    def get_comm_channels(self) -> dict:
        return self.comm_channels

    def get_api(self, name: str) -> dict:
        if name not in self.apis:
            logger.warning(f"Api '{name}' not found")
            return {}
        return self.apis[name]


class BusClaims:
    """What the created buses and Modbus devices occupy, a second claim is an error of the config"""

    def __init__(self):
        # the circuits of the created Modbus devices -> their bus, the circuit is only the name of the device
        self.names: dict[str, str] = {}
        # the real paths of the serial ports -> their bus, two buses would mix their requests on one line
        # and its transport, see link_serial_ports()
        self.serial_ports: dict[str, tuple[str, BusTransport]] = {}
        # (line, slave-id) -> the device and its bus, the line is the serial port or (host, port) of TCP
        self.units: dict[tuple, tuple[str, str]] = {}
        # the 1-Wire master (None is the first one) -> its OWFS bus, two buses created all its sensors twice
        self.w1_masters: dict[str | None, str] = {}
        # (the Client of a unit, its option serial_ports), linked after all buses are created
        self.serial_links: list[tuple[object, list[str]]] = []


def create_devices(evok_config: EvokConfig, hw_dict):
    claims = BusClaims()
    for bus_name, bus_data in evok_config.get_comm_channels().items():
        # an error in the config of a bus does not stop creating the other buses
        try:
            _create_bus(bus_name, bus_data or {}, hw_dict, claims)
        except Exception:
            logger.exception(f"Error in config of bus '{bus_name}'")
    link_serial_ports(claims)


def link_serial_ports(claims: BusClaims):
    """Give the units the serial buses of the ports they serve (serial_ports of the device), held by their
    nv_save and reset; a port of no MODBUSRTU bus is skipped, e.g. a port used by another program
    """
    for client, ports in claims.serial_links:
        buses = {}
        for port in ports:
            path = os.path.realpath(port)
            if path in claims.serial_ports:
                buses[path] = claims.serial_ports[path][1]
        client.serial_buses = [buses[path] for path in sorted(buses)]


def bus_retries(bus_data: dict) -> int:
    """The option retries of a Modbus bus, the count of retries of a request, 1 by default"""
    retries = bus_data.get("retries", 1)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError(f"retries must be an integer >= 0, not '{retries}'")
    return retries


def probe_timeout(bus_data: dict, default: float) -> float:
    """The option probe_timeout of a Modbus bus, the timeout of a request to a unit which does not respond"""
    value = bus_data.get("probe_timeout", default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not value > 0:
        raise ValueError(f"probe_timeout must be a positive number, not '{value}'")
    return float(value)


def retry_strategies(timeout: float, connect_timeout: float, retries: int = 1) -> dict:
    """Retries of AsyncSmartTransport, which fail fast

    The bus is locked during the retries, the default ones of tmodbus took up to 60 s
    for each request to an unavailable unit and the other units of the bus waited.
    A unit which does not respond is slowed down by its ModbusScanner.
    """
    attempts = retries + 1
    return {
        # one attempt, its failure is a ModbusConnectionError; it also opens the connection
        # before the first request, the bus is not opened by Evok, a failed open was not reported
        "auto_reconnect": AsyncRetrying(stop=stop_after_attempt(1), wait=wait_fixed(0)),
        # the retries of the request, e.g. with a new connection after a lost one;
        # retry_never: the default retry of AsyncRetrying is any exception, the transport adds its reasons
        "response_retry_strategy": AsyncRetrying(
            retry=retry_never,
            stop=stop_after_attempt(attempts) | stop_after_delay(attempts * (timeout + connect_timeout)),
            wait=wait_fixed(0.1),
        ),
    }


def _create_bus(bus_name, bus_data: dict, hw_dict, claims: BusClaims):
    if not bus_data.get("enabled", True):
        logger.info(f"Skipping disabled bus '{bus_name}'")
        return
    bus_type = bus_data.get("type")

    bus = None
    line = None
    bus_device_info: DeviceInfo | None = None
    if bus_type == "OWFS":
        interval = bus_data.get("interval", 60)
        scan_interval = bus_data.get("scan_interval", 300)
        owpower = bus_data.get("owpower")
        for option in ("hostname", "port"):
            if option in bus_data:
                # owserver is not used, the bus is read by the kernel
                raise EvokConfigError(
                    f"'{option}' of an OWFS bus is not supported, use 'master' "
                    f"(the 1-Wire master of the kernel, e.g. w1_bus_master1)"
                )
        master = bus_data.get("master")
        if master is not None and (not isinstance(master, str) or not master.startswith("w1_bus_master")):
            raise EvokConfigError(
                f"master must be the name of a 1-Wire master of the kernel, e.g. w1_bus_master1, not '{master}'"
            )
        if master in claims.w1_masters:
            raise EvokConfigError(
                f"1-Wire master {master or '(the first one)'} is already used by bus '{claims.w1_masters[master]}'"
            )

        circuit = bus_name
        bus = w1.OwBusDriver(
            circuit, interval=interval, scan_interval=scan_interval, owpower_circuit=owpower, master=master
        )
        Devices.register_device(OWBUS, bus)
        claims.w1_masters[master] = bus_name

    elif bus_type == "MODBUSTCP":
        host = bus_data.get("hostname", "127.0.0.1")
        port = bus_data.get("port", 502)
        timeout = float(bus_data.get("timeout", 0.5))
        connect_timeout = float(bus_data.get("connect_timeout", 1.0))
        retries = bus_retries(bus_data)
        # a gateway on the network may need the whole timeout
        probe = probe_timeout(bus_data, timeout)
        bus_driver = BusTransport(
            AsyncTcpTransport(host, port, timeout=timeout, connect_timeout=connect_timeout),
            wait_between_requests=0.0,
            wait_after_connect=0.0,
            retry_on_device_busy=True,
            retry_on_device_failure=False,
            probe_timeout=probe,
            **retry_strategies(timeout, connect_timeout, retries),
        )
        bus = TcpBusDevice(
            circuit=bus_name,
            bus_driver=bus_driver,
            hostname=host,
            port=port,
            timeout=timeout,
            connect_timeout=connect_timeout,
            retries=retries,
            probe_timeout=probe,
        )
        # more buses may connect to one server, its units must differ
        line = ("tcp", str(host).lower(), port)
        Devices.register_device(TCPBUS, bus)

    elif bus_type == "MODBUSRTU":
        serial_port = bus_data["port"]
        # e.g. a symlink of /dev/ttyNS0
        line = ("rtu", os.path.realpath(serial_port))
        if line[1] in claims.serial_ports:
            raise EvokConfigError(
                f"Serial port '{serial_port}' is already used by bus '{claims.serial_ports[line[1]][0]}'"
            )
        serial_baud_rate = bus_data.get("baudrate", 19200)
        serial_parity = bus_data.get("parity", "N")
        serial_stopbits = bus_data.get("stopbits", 1)
        timeout = float(bus_data.get("timeout", 0.5))
        retries = bus_retries(bus_data)
        # a response on a serial line comes in a few ms, the units of the bus wait for the probe
        probe = probe_timeout(bus_data, min(0.1, timeout))
        bus_driver = BusTransport(
            AsyncRtuTransport(
                serial_port, timeout=timeout, baudrate=serial_baud_rate, parity=serial_parity, stopbits=serial_stopbits
            ),
            wait_between_requests=0.0,
            wait_after_connect=0.0,
            retry_on_device_busy=True,
            retry_on_device_failure=False,
            # the serial port is opened at once, its timeout is the response timeout
            probe_timeout=probe,
            **retry_strategies(timeout, timeout, retries),
        )
        bus = SerialBusDevice(
            circuit=bus_name,
            bus_driver=bus_driver,
            port=serial_port,
            baudrate=serial_baud_rate,
            parity=serial_parity,
            stopbits=serial_stopbits,
            timeout=timeout,
            retries=retries,
            probe_timeout=probe,
        )
        Devices.register_device(SERIALBUS, bus)
        claims.serial_ports[line[1]] = (bus_name, bus_driver)

    else:
        # e.g. 'OWBUS', the 1-Wire bus type before it was renamed to 'OWFS'
        logger.error(f"Unknown type '{bus_type}' of bus '{bus_name}'! skipping...")
        return

    if bus is not None:
        bus_device_info_data = bus_data.get("device_info")
        if bus_device_info_data is not None:
            bus_device_info_data: dict
            family = bus_device_info_data.get("family", "unknown")
            model = bus_device_info_data.get("model", "unknown")
            sn = bus_device_info_data.get("sn", None)
            board_count = bus_device_info_data.get("board_count", 1)
            bus_device_info = DeviceInfo(name=model, family=family, model=model, sn=sn, board_count=board_count)
            Devices.register_device(DEVICE_INFO, bus_device_info)

    if "devices" not in bus_data:
        logger.info(f"Creating bus '{bus_name}' with type '{bus_type}'.")
        return

    logger.info(f"Creating bus '{bus_name}' with type '{bus_type}' with devices.")
    for device_name, device_data in (bus_data["devices"] or {}).items():
        device_data = device_data or {}
        if not device_data.get("enabled", True):
            logger.info(f"^ Skipping disabled device '{device_name}'")
            continue
        logger.info(f"^ Creating device '{device_name}' with type '{bus_type}'")
        try:
            if bus_type == "OWFS":
                ow_type = device_data.get("type")
                address = device_data.get("address")
                if address is None:
                    raise EvokConfigError("Missing 'address' of the 1-Wire sensor")
                interval = int(device_data.get("interval", 15))

                # the sensor registers itself in the bus and in Devices
                sensor = w1.MySensorFabric(address, ow_type, bus, interval=interval, circuit=str(device_name))
                if sensor is None:
                    raise EvokConfigError(f"Unsupported type '{ow_type}' of the 1-Wire sensor")

            elif bus_type in ["MODBUSTCP", "MODBUSRTU"]:
                slave_id = device_data.get("slave-id", 1)
                scanfreq = device_data.get("scan_frequency", 50)
                scan_enabled = device_data.get("scan_enabled", True)
                device_model = device_data["model"]
                circuit = str(device_name)
                # the second device replaced the first one in Devices and its IOs were not created
                if circuit in claims.names:
                    raise EvokConfigError(
                        f"Modbus device '{circuit}' of bus '{bus_name}' has the same name "
                        f"as the device of bus '{claims.names[circuit]}', rename one of them"
                    )
                if device_model not in hw_dict.definitions:
                    logger.error("Unsupported device model %s. Check HW definitions", device_model)
                    raise EvokConfigError("")
                hw_model_dict = hw_dict.definitions[device_model]
                # an empty option is no port, as the other empty sections
                serial_ports = device_data.get("serial_ports") or []
                if not isinstance(serial_ports, list) or not all(isinstance(port, str) for port in serial_ports):
                    raise EvokConfigError(
                        f"serial_ports must be a list of the serial ports served by the device, "
                        f"e.g. [/dev/ttyNS0], not '{serial_ports}'"
                    )
                # a unit of a serial bus holding another one could wait for it while it holds its bus
                if serial_ports and bus_type != "MODBUSTCP":
                    raise EvokConfigError("serial_ports is an option of a device of a MODBUSTCP bus, e.g. a local unit")

                slave = ModbusScanner(bus.bus_driver, circuit, scanfreq, scan_enabled, hw_model_dict, unit_id=slave_id)
                # the scanner validated the slave-id, two devices would read and write the same unit
                unit = (line, slave.modbus_address)
                if unit in claims.units:
                    other, other_bus = claims.units[unit]
                    raise EvokConfigError(
                        f"Modbus device '{circuit}' of bus '{bus_name}' has the same slave-id "
                        f"{slave.modbus_address} as the device '{other}' of bus '{other_bus}'"
                    )
                Devices.register_device(MODBUS_SLAVE, slave)
                claims.names[circuit] = bus_name
                claims.units[unit] = (circuit, bus_name)
                bus.devices.append(circuit)
                if serial_ports:
                    claims.serial_links.append((slave.client, serial_ports))

                if bus_device_info is None or "device_info" in device_data:
                    device_info = {"model": device_data.get("model", device_name)}
                    device_info.update(device_data.get("device_info", {}))
                    family = device_info.get("family", "unknown")
                    model = device_info.get("model", "unknown")
                    sn = device_info.get("sn")
                    board_count = device_info.get("board_count", 1)
                    if model[:2].lower() in ["xs", "xm", "xl", "xg"] and family == "unknown":
                        family = "Extension"
                    Devices.register_device(
                        DEVICE_INFO,
                        DeviceInfo(name=device_name, family=family, model=model, sn=sn, board_count=board_count),
                    )

        except Exception:
            logger.exception(f"Error in config section '{bus_type}:{device_name}'")


def load_aliases(path):
    # the file is read whatever its extension is, it is overwritten by save_aliases()
    alias_conf = {}
    try:
        with open(path) as f:
            alias_conf = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.info(f"Alias file {path} not found, no aliases are loaded")
    except (OSError, yaml.YAMLError) as E:
        logger.error(f"Cannot load alias file {path}: {E}")
    if not isinstance(alias_conf, dict):
        logger.error(f"Alias file {path} does not contain a mapping, aliases are not loaded")
        alias_conf = {}
    # 'version: 2.0' without quotes is a number, without a version it is given by the format of the aliases
    version = alias_conf.get("version")
    if version is None:
        version = "1.0" if isinstance(alias_conf.get("aliases"), list) else "2.0"
    version = str(version)
    if version in ("1", "1.0"):
        # transform array to dict and rename dev_type -> devtype if version 1.0
        result = {
            rec["name"]: {"circuit": rec.get("circuit", None), "devtype": rec.get("dev_type", None)}
            for rec in alias_conf.get("aliases", {})
            if rec.get("name", None) is not None
        }
    elif version in ("2", "2.0"):
        result = alias_conf.get("aliases") or {}
    else:
        logger.error(f"Unknown version '{version}' of the alias file {path}, aliases are not loaded")
        result = {}
    Devices.aliases = Aliases(result)
    logger.debug(f"Load aliases with {result}")


# don't call it directly in asyn loop -- block
def save_aliases(alias_dict, path):
    """Write the aliases to a temporary file and replace the file by it, so a failed write
    keeps the previous file. An error is raised to the caller, which tries it again later.
    """
    logger.info(f"Saving alias file {path}")
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as yfile:
        yfile.write(yaml.dump({"version": "2.0", "aliases": alias_dict}))
        yfile.flush()
        os.fsync(yfile.fileno())
    os.replace(tmp_path, path)
    # the rename is durable after the directory is synced
    dir_fd = os.open(os.path.dirname(os.path.abspath(path)), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
