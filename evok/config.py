import os
from typing import List, Dict, Union
from tornado.ioloop import IOLoop

from .modbus_unipi import EvokModbusSerialClient, EvokModbusTcpClient
from .modbus_slave import ModbusSlave
from . import owdevice

import yaml
from .devices import *


class EvokConfigError(Exception):
    pass


class HWDict:
    def __init__(self, dir_paths: List[str] = None, paths: List[str] = None):
        """
        :param dir_paths: path to dir for load
        :param paths: paths to config files
        """
        self.definitions: Dict[str, List] = {}
        scope = list()
        if dir_paths is not None:
            for dp in dir_paths:
                if not os.path.exists(dp) or not os.path.isdir(dp):
                    logger.error(f"HWDict: Entered path is not directory: '{dp}'!")
                    continue
                scope.extend([dp + f for f in os.listdir(dp)])
        if paths is not None:
            scope.extend(paths)
        if scope is None or len(scope) == 0:
            logger.warning(f"HWDict: no scope!")
        else:
            for file_path in scope:
                if file_path.endswith(".yaml") and os.path.isfile(file_path):
                    file_name = file_path.split("/")[-1].replace(".yaml", "")
                    with open(file_path, 'r') as yfile:
                        ydata = yaml.load(yfile, Loader=yaml.SafeLoader)
                        if ydata is None:
                            logger.warning(f"Empty Definition file '{file_path}'! skipping...")
                            continue
                        self.definitions[file_name] = ydata
                        logger.debug(f"YAML Definition loaded: {file_path}, definition count {len(self.definitions) - 1}")


class OWSensorDevice:
    def __init__(self, sensor_dev):
        self.sensor_dev = sensor_dev
        self.circuit = sensor_dev.circuit

    def full(self):
        return self.sensor_dev.full()


class TcpBusDevice:
    def __init__(self, circuit: str, bus_driver: EvokModbusTcpClient):
        self.bus_driver = bus_driver
        self.circuit = circuit

    def switch_to_async(self, loop: IOLoop):
        loop.add_callback(lambda: self.bus_driver.connect())


class SerialBusDevice:
    def __init__(self, circuit: str,  bus_driver: EvokModbusSerialClient):
        self.bus_driver = bus_driver
        self.circuit = circuit

    def switch_to_async(self, loop: IOLoop):
        self.bus_driver.ioloop = loop
        loop.add_callback(lambda: self.bus_driver.connect())


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
        data = self.__get_final_conf(scope=[conf_dir_path+'/config.yaml'])
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

    def __get_final_conf(self, conf_dir_path: Union[None, str] = None,
                         scope: Union[None, List[str]] = None,
                         check_autogen: bool = True) -> dict:
        if scope is None:
            files = os.listdir(conf_dir_path)
            if 'config.yaml' not in files:
                raise EvokConfigError(f"Missing 'config.yaml' in evok configuration directory ({conf_dir_path})")
            scope = files
        final_conf = {}
        for path in scope:
            try:
                with open(path, 'r') as f:
                    ydata: dict = yaml.load(f, Loader=yaml.Loader)
                self.__merge_data(final_conf, ydata)
            except FileNotFoundError:
                logger.warning(f"Config file {path} not found!")
        if check_autogen and final_conf.get('autogen', False):
            return self.__get_final_conf(scope=['/etc/evok/autogen.yaml', *scope], check_autogen=False)
        return final_conf

    @staticmethod
    def __get_comm_channels(data: dict) -> dict:
        ret = {}
        if 'comm_channels' not in data:
            logger.warning("Section 'comm_channels' not in configuration!")
            return ret
        for name, value in data['comm_channels'].items():
            ret[name] = value
        return ret

    @staticmethod
    def __get_apis_conf(data: dict) -> dict:
        ret = {}
        if 'apis' not in data:
            logger.warning("Section 'apis' not in configuration!")
            return ret
        for name, value in data['apis'].items():
            ret[name] = value
        return ret

    @staticmethod
    def __get_logging_conf(data: dict) -> dict:
        ret = {}
        if 'logging' not in data:
            logger.warning("Section 'logging' not in configuration!")
            return ret
        for name, value in data['logging'].items():
            ret[name] = value
        return ret

    def configtojson(self):
        return self.main  # TODO: zkontrolovat!!

    def get_comm_channels(self) -> dict:
        return self.comm_channels

    def get_api(self, name: str) -> dict:
        if name not in self.apis:
            logging.warning(f"Api '{name}' not found")
            return {}
        return self.apis[name]


def hexint(value):
    if value.startswith('0x'):
        return int(value[2:], 16)
    return int(value)


def create_devices(evok_config: EvokConfig, hw_dict):
    for bus_name, bus_data in evok_config.get_comm_channels().items():
        bus_data: dict
        if not bus_data.get("enabled", True):
            logger.info(f"Skipping disabled bus '{bus_name}'")
            continue
        bus_type = bus_data['type']

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
            modbus_server = bus_data.get("hostname", "127.0.0.1")
            modbus_port = bus_data.get("port", 502)
            bus_driver = EvokModbusTcpClient(host=modbus_server, port=modbus_port)
            bus = TcpBusDevice(circuit=bus_name, bus_driver=bus_driver)
            Devices.register_device(TCPBUS, bus)

        elif bus_type == "MODBUSRTU":
            serial_port = bus_data["port"]
            serial_baud_rate = bus_data.get("baudrate", 19200)
            serial_parity = bus_data.get("parity", 'N')
            serial_stopbits = bus_data.get("stopbits", 1)
            bus_driver = EvokModbusSerialClient(port=serial_port, baudrate=serial_baud_rate, parity=serial_parity,
                                                stopbits=serial_stopbits, timeout=0.5)
            bus = SerialBusDevice(circuit=bus_name, bus_driver=bus_driver)
            Devices.register_device(SERIALBUS, bus)

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
            continue

        logger.info(f"Creating bus '{bus_name}' with type '{bus_type}' with devices.")
        for device_name, device_data in bus_data['devices'].items():
            if not device_data.get("enabled", True):
                logger.info(f"^ Skipping disabled device '{device_name}'")
                continue
            logger.info(f"^ Creating device '{device_name}' with type '{bus_type}'")
            try:
                if bus_type == 'OWBUS':
                    ow_type = device_data.get("type")
                    address = device_data.get("address")
                    interval = device_data.getintdef("interval", 15)

                    circuit = device_name
                    sensor = owdevice.MySensorFabric(address, ow_type, bus, interval=interval, circuit=circuit,
                                                     is_static=True)
                    if sensor is not None:
                        sensor = OWSensorDevice(sensor)
                    Devices.register_device(SENSOR, sensor)

                elif bus_type in ['MODBUSTCP', 'MODBUSRTU']:
                    slave_id = device_data.get("slave-id", 1)
                    scanfreq = device_data.get("scan_frequency", 50)
                    scan_enabled = device_data.get("scan_enabled", True)
                    device_model = device_data["model"]
                    circuit = f"{device_name}"
                    major_group = device_name

                    slave = ModbusSlave(bus.bus_driver, circuit, evok_config, scanfreq, scan_enabled,
                                        hw_dict, device_model=device_model, slave_id=slave_id,
                                        major_group=major_group)
                    Devices.register_device(MODBUS_SLAVE, slave)

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

                else:
                    logger.error(f"Unknown bus type: '{bus_type}'! skipping...")
                    if logger.level == logging.DEBUG:
                        traceback.print_exc()

            except Exception as E:
                logger.exception(f"Error in config section '{bus_type}:{device_name}' - {str(E)}")


def load_aliases(path):
    alias_dicts = list(HWDict(paths=[path]).definitions.values())
    # HWDict returns List(), take only first item
    alias_conf = alias_dicts[0] if len(alias_dicts) > 0 else dict()
    version = str(alias_conf.get("version", "1.0"))

    version = alias_conf.get("version", None)
    if version == "1.0":
        # transform array to dict and rename dev_type -> devtype if version 1.0
        result = dict(((rec["name"], {"circuit": rec.get("circuit", None), "devtype": rec.get("dev_type", None)})\
                       for rec in alias_conf.get("aliases", {})\
                       if rec.get("name", None) is not None))
    elif version == "2.0":
        result = alias_conf.get("aliases", {})
    else:
        result = {}
    Devices.aliases = Aliases(result)
    logger.debug(f"Load aliases with {result}")


# don't call it directly in asyn loop -- block
def save_aliases(alias_dict, path):
    try:
        logger.info(f"Saving alias file {path}")
        with open(path, 'w+') as yfile:
            yfile.write(yaml.dump({"version": "2.0", "aliases": alias_dict}))
        os.system('sync')
    except Exception as E:
        logger.exception(str(E))
