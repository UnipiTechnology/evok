import os
from typing import List, Dict, Union

from .modbus import ModbusScanner
from tenacity import AsyncRetrying, retry_never, stop_after_attempt, stop_after_delay, wait_fixed
from tmodbus import (
    AsyncRtuTransport,
    AsyncSmartTransport,
    AsyncTcpTransport,
)

from . import owdevice

import yaml
from .devices import Devices, Aliases
from .devices import OWBUS, SERIALBUS, DEVICE_INFO, TCPBUS, MODBUS_SLAVE
from .log import logger


class EvokConfigError(Exception):
    pass


class HWDict:
    def __init__(self, dir_paths: List[str] = None, paths: List[str] = None):
        """
        :param dir_paths: paths to directories with definitions, all '.yaml' files are loaded
        :param paths: paths to definition files
        """
        self.definitions: Dict[str, dict] = {}
        scope = list()
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
            file_name = os.path.basename(file_path)[:-len(".yaml")]
            # an invalid file is skipped, the other definitions are loaded
            try:
                with open(file_path, 'r') as yfile:
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


class TcpBusDevice:
    """ The connection is opened by the first request, see retry_strategies() """

    def __init__(self, circuit: str, bus_driver: AsyncSmartTransport):
        self.bus_driver = bus_driver
        self.circuit = circuit


class SerialBusDevice:
    """ The serial port is opened by the first request, see retry_strategies() """

    def __init__(self, circuit: str, bus_driver: AsyncSmartTransport):
        self.bus_driver = bus_driver
        self.circuit = circuit


class DeviceInfo:
    def __init__(self, name: str, family: str, model: str, sn: Union[None, int], board_count: int):
        """
        :param family: [Neuron, Patron, UNIPI1, Iris]
        :param model: [S103, M533, ...]
        :param sn: serial number
        :param board_count: number of boards
        """
        self.family: str = family
        self.model: str = model
        self.sn: Union[None, int] = sn
        self.board_count: int = board_count
        self.circuit: str = f"{name}"

    def full(self):
        return {
            'dev': "device_info",
            'family': self.family,
            'model': self.model,
            'sn': self.sn,
            'board_count': self.board_count,
            'circuit': self.circuit,
        }


class EvokConfig:

    def __init__(self, conf_dir_path: str):
        self.conf_dir_path = conf_dir_path
        data = self.__get_final_conf([conf_dir_path + '/config.yaml'])
        self.comm_channels: dict = self.__get_comm_channels(data)
        self.apis: dict = self.__get_apis_conf(data)
        self.logging: dict = self.__get_logging_conf(data)

    def __merge_data(self, source: dict, append: dict):
        for key in append:
            if key in source and type(source[key]) == dict and type(append[key]) == dict:
                source[key] = self.__merge_data(source[key], append[key])
            else:
                source[key] = append[key]
        return source

    def __get_final_conf(self, scope: List[str], check_autogen: bool = True) -> dict:
        """ Merge the config files in the scope, the later ones override the former ones """
        final_conf = {}
        for path in scope:
            try:
                with open(path, 'r') as f:
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
        if check_autogen and final_conf.get('autogen', False):
            return self.__get_final_conf([self.conf_dir_path + '/autogen.yaml', *scope], check_autogen=False)
        return final_conf

    @staticmethod
    def __get_comm_channels(data: dict) -> dict:
        ret = {}
        if 'comm_channels' not in data:
            logger.warning("Section 'comm_channels' not in configuration!")
            return ret
        for name, value in (data['comm_channels'] or {}).items():
            ret[name] = value
        return ret

    @staticmethod
    def __get_apis_conf(data: dict) -> dict:
        ret = {}
        if 'apis' not in data:
            logger.warning("Section 'apis' not in configuration!")
            return ret
        for name, value in (data['apis'] or {}).items():
            ret[name] = value
        return ret

    @staticmethod
    def __get_logging_conf(data: dict) -> dict:
        ret = {}
        if 'logging' not in data:
            logger.warning("Section 'logging' not in configuration!")
            return ret
        for name, value in (data['logging'] or {}).items():
            ret[name] = value
        return ret

    def get_comm_channels(self) -> dict:
        return self.comm_channels

    def get_api(self, name: str) -> dict:
        if name not in self.apis:
            logger.warning(f"Api '{name}' not found")
            return {}
        return self.apis[name]


def create_devices(evok_config: EvokConfig, hw_dict):
    # the circuits of the created Modbus devices -> their bus, the circuit is only the name of the device
    modbus_names: Dict[str, str] = {}
    for bus_name, bus_data in evok_config.get_comm_channels().items():
        # an error in the config of a bus does not stop creating the other buses
        try:
            _create_bus(bus_name, bus_data or {}, hw_dict, modbus_names)
        except Exception as E:
            logger.exception(f"Error in config of bus '{bus_name}' - {str(E)}")


def bus_retries(bus_data: dict) -> int:
    """ The option retries of a Modbus bus, the count of retries of a request, 1 by default """
    retries = bus_data.get("retries", 1)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ValueError(f"retries must be an integer >= 0, not '{retries}'")
    return retries


def retry_strategies(timeout: float, connect_timeout: float, retries: int = 1) -> dict:
    """ Retries of AsyncSmartTransport, which fail fast

        The bus is locked during the retries, the default ones of tmodbus took up to 60 s
        for each request to an unavailable unit and the other units of the bus waited.
        A unit which does not respond is slowed down by its ModbusScanner.
    """
    attempts = retries + 1
    return dict(
        # one attempt, its failure is a ModbusConnectionError; it also opens the connection
        # before the first request, the bus is not opened by Evok, a failed open was not reported
        auto_reconnect=AsyncRetrying(stop=stop_after_attempt(1), wait=wait_fixed(0)),
        # the retries of the request, e.g. with a new connection after a lost one;
        # retry_never: the default retry of AsyncRetrying is any exception, the transport adds its reasons
        response_retry_strategy=AsyncRetrying(
            retry=retry_never,
            stop=stop_after_attempt(attempts) | stop_after_delay(attempts * (timeout + connect_timeout)),
            wait=wait_fixed(0.1),
        ),
    )


def _create_bus(bus_name, bus_data: dict, hw_dict, modbus_names: Dict[str, str]):
    if not bus_data.get("enabled", True):
        logger.info(f"Skipping disabled bus '{bus_name}'")
        return
    bus_type = bus_data.get('type')

    bus = None
    bus_device_info: Union[None, DeviceInfo] = None
    if bus_type == 'OWFS':
        interval = bus_data.get("interval", 60)
        scan_interval = bus_data.get("scan_interval", 300)
        owpower = bus_data.get("owpower", None)

        circuit = bus_name
        bus = owdevice.OwBusDriver(circuit, interval=interval, scan_interval=scan_interval,
                                   owpower_circuit=owpower)
        Devices.register_device(OWBUS, bus)

    elif bus_type == 'MODBUSTCP':
        host = bus_data.get("hostname", "127.0.0.1")
        port = bus_data.get("port", 502)
        timeout = float(bus_data.get("timeout", 0.5))
        connect_timeout = float(bus_data.get("connect_timeout", 1.0))
        bus_driver = AsyncSmartTransport(
            AsyncTcpTransport(
                host,
                port,
                timeout=timeout,
                connect_timeout=connect_timeout
            ),
            wait_between_requests=0.0,
            wait_after_connect=0.0,
            retry_on_device_busy=True,
            retry_on_device_failure=False,
            **retry_strategies(timeout, connect_timeout, bus_retries(bus_data)),
        )
        bus = TcpBusDevice(circuit=bus_name, bus_driver=bus_driver)
        Devices.register_device(TCPBUS, bus)

    elif bus_type == "MODBUSRTU":
        serial_port = bus_data["port"]
        serial_baud_rate = bus_data.get("baudrate", 19200)
        serial_parity = bus_data.get("parity", 'N')
        serial_stopbits = bus_data.get("stopbits", 1)
        timeout = float(bus_data.get("timeout", 0.5))
        bus_driver = AsyncSmartTransport(
            AsyncRtuTransport(
                serial_port,
                timeout=timeout,
                baudrate=serial_baud_rate,
                parity=serial_parity,
                stopbits=serial_stopbits),
            wait_between_requests=0.0,
            wait_after_connect=0.0,
            retry_on_device_busy=True,
            retry_on_device_failure=False,
            # the serial port is opened at once, its timeout is the response timeout
            **retry_strategies(timeout, timeout, bus_retries(bus_data)),
        )
        bus = SerialBusDevice(circuit=bus_name, bus_driver=bus_driver)
        Devices.register_device(SERIALBUS, bus)

    else:
        # e.g. 'OWBUS', the 1-Wire bus type before it was renamed to 'OWFS'
        logger.error(f"Unknown type '{bus_type}' of bus '{bus_name}'! skipping...")
        return

    if bus is not None:
        bus_device_info_data = bus_data.get("device_info", None)  # noqa
        if bus_device_info_data is not None:
            bus_device_info_data: dict
            family = bus_device_info_data.get("family", 'unknown')
            model = bus_device_info_data.get("model", 'unknown')
            sn = bus_device_info_data.get("sn", None)
            board_count = bus_device_info_data.get("board_count", 1)
            bus_device_info = DeviceInfo(name=model, family=family, model=model, sn=sn, board_count=board_count)
            Devices.register_device(DEVICE_INFO, bus_device_info)

    if 'devices' not in bus_data:
        logger.info(f"Creating bus '{bus_name}' with type '{bus_type}'.")
        return

    logger.info(f"Creating bus '{bus_name}' with type '{bus_type}' with devices.")
    for device_name, device_data in (bus_data['devices'] or {}).items():
        device_data = device_data or {}
        if not device_data.get("enabled", True):
            logger.info(f"^ Skipping disabled device '{device_name}'")
            continue
        logger.info(f"^ Creating device '{device_name}' with type '{bus_type}'")
        try:
            if bus_type == 'OWFS':
                ow_type = device_data.get("type")
                address = device_data.get("address")
                if address is None:
                    raise EvokConfigError("Missing 'address' of the 1-Wire sensor")
                interval = int(device_data.get("interval", 15))

                # the sensor registers itself in the bus and in Devices
                sensor = owdevice.MySensorFabric(address, ow_type, bus, interval=interval, circuit=str(device_name))
                if sensor is None:
                    raise EvokConfigError(f"Unsupported type '{ow_type}' of the 1-Wire sensor")

            elif bus_type in ['MODBUSTCP', 'MODBUSRTU']:
                slave_id = device_data.get("slave-id", 1)
                scanfreq = device_data.get("scan_frequency", 50)
                scan_enabled = device_data.get("scan_enabled", True)
                device_model = device_data["model"]
                circuit = str(device_name)
                # the second device replaced the first one in Devices and its IOs were not created
                if circuit in modbus_names:
                    raise EvokConfigError(f"Modbus device '{circuit}' of bus '{bus_name}' has the same name "
                                          f"as the device of bus '{modbus_names[circuit]}', rename one of them")
                if device_model not in hw_dict.definitions:
                    logger.error("Unsupported device model %s. Check HW definitions",
                                 device_model)
                    raise EvokConfigError("")
                hw_model_dict = hw_dict.definitions[device_model]

                slave = ModbusScanner(bus.bus_driver, circuit, scanfreq, scan_enabled,
                                      hw_model_dict, unit_id=slave_id)
                Devices.register_device(MODBUS_SLAVE, slave)
                modbus_names[circuit] = bus_name

                if bus_device_info is None or "device_info" in device_data:
                    device_info = {'model': device_data.get("model", device_name)}
                    device_info.update(device_data.get("device_info", {}))
                    family = device_info.get("family", 'unknown')
                    model = device_info.get("model", 'unknown')
                    sn = device_info.get("sn", None)
                    board_count = device_info.get("board_count", 1)
                    if model[:2].lower() in ['xs', 'xm', 'xl', 'xg'] and family == 'unknown':
                        family = 'Extension'
                    Devices.register_device(DEVICE_INFO,
                                            DeviceInfo(name=device_name, family=family, model=model, sn=sn,
                                                       board_count=board_count))

        except Exception as E:
            logger.exception(f"Error in config section '{bus_type}:{device_name}' - {str(E)}")


def load_aliases(path):
    # the file is read whatever its extension is, it is overwritten by save_aliases()
    alias_conf = {}
    try:
        with open(path, 'r') as f:
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
        result = dict(((rec["name"], {"circuit": rec.get("circuit", None), "devtype": rec.get("dev_type", None)})
                       for rec in alias_conf.get("aliases", {})
                       if rec.get("name", None) is not None))
    elif version in ("2", "2.0"):
        result = alias_conf.get("aliases") or {}
    else:
        logger.error(f"Unknown version '{version}' of the alias file {path}, aliases are not loaded")
        result = {}
    Devices.aliases = Aliases(result)
    logger.debug(f"Load aliases with {result}")


# don't call it directly in asyn loop -- block
def save_aliases(alias_dict, path):
    """ Write the aliases to a temporary file and replace the file by it, so a failed write
        keeps the previous file. An error is raised to the caller, which tries it again later.
    """
    logger.info(f"Saving alias file {path}")
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w') as yfile:
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
