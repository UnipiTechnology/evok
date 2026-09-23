import logging
import traceback

from . import devents
import re
from copy import deepcopy
from typing import Any, Callable, Union

from .errors import DeviceNotFound
from .log import logger

"""
   Structured dict/dict of all devices in the system

"""

# ToDo: ...
Device = Any


class Aliases:
    alias_dict: dict[str, Device] = {}
    initial_dict: dict[str, dict[str, str]] = {}

    def __init__(self, initial_dict: dict[str, dict[str, str]]):
        self.devtype = 'run'
        self.circuit = 'alias'
        for key, value in initial_dict.items():
            try:
                value['devtype'] = num_to_devtype_name[int(value['devtype'])]
                logger.warning(f"Aliases: Detected old devtype '{key}'! Upgrading...")
            except ValueError:
                pass
            self.initial_dict[key] = value
        self.dirty_callback: Union[None, Callable] = None
        self.save_callback: Union[None, Callable] = None

    def __getitem__(self, key):
        return self.alias_dict.__getitem__(key)

    def __contains__(self, key):
        return self.alias_dict.__contains__(key)

    def register_dirty_cb(self, func: Callable) -> None:
        self.dirty_callback = func

    def register_save_cb(self, func: Callable) -> None:
        self.save_callback = func

    def set_dirty(self) -> None:
        if self.dirty_callback:
            self.dirty_callback()

    def set_force_save(self) -> None:
        if self.save_callback:
            self.save_callback()

    def validate(self, alias: str) -> None:
        # check duplicity
        if alias in self.alias_dict:
            raise Exception(f"Duplicate alias {alias}")
        # check alias name
        if len(re.findall(r"[A-Za-z0-9\-\._]*", alias)) > 2:
            raise Exception(f"Invalid alias {alias}")

    def add(self, alias: str, device: Device, file_update: bool = False):
        if alias != device.alias:
            self.validate(alias)
        # delete old alias
        if device.alias: self.delete(device.alias)
        # delete alias from initial_dict
        if alias: self.delete(alias)
        # create new alias
        self.alias_dict[alias] = device
        if file_update:
            self.set_force_save()
        else:
            self.set_dirty()

    def delete(self, alias: str, file_update: bool = False) -> None:
        # delete alias from regular dict
        if alias in self.alias_dict:
            del self.alias_dict[alias]
            if file_update:
                self.set_force_save()
            else:
                self.set_dirty()
        # delete alias from initial dict
        if alias in self.initial_dict:
            del self.initial_dict[alias]
            if file_update:
                self.set_force_save()
            else:
                self.set_dirty()

    def get_aliases_by_circuit(self, devtype: int, circuit: str):
        return list((alias for alias, rec in self.initial_dict.items() \
                     if (rec.get("devtype", None) == devtype) and (rec.get("circuit", None) == circuit)))

    def get_dict_to_save(self) -> dict[str, dict[str, str]]:
        aliases = deepcopy(self.initial_dict)
        aliases.update(dict(((alias, {"circuit": device.circuit, "devtype": device.devtype})
                             for alias, device in self.alias_dict.items())))
        return aliases

    @property
    def aliases(self) -> dict:
        return {k:{"circuit": f"{v.devtype}_{v.circuit}",
                   "devtype": v.devtype}
                for k, v in self.alias_dict.items()}

    def full(self):
        ret = {
            'dev': 'run',
            'circuit': self.circuit,
            'save': False,
            'aliases': self.aliases
        }
        return ret

    async def set(self, save: bool = False):
        if save is not None and bool(int(save)):
            self.set_force_save()
        return self.full()


class DeviceList(dict):
    aliases = Aliases({})

    def __init__(self, altnames):
        super(DeviceList, self).__init__()
        self.altnames = altnames

    def __setitem__(self, key, value):
        super(DeviceList, self).__setitem__(key, value)

    def __getitem__(self, key):
        try:
            return super(DeviceList, self).__getitem__(key)
        except KeyError:
            return super(DeviceList, self).__getitem__(self.altnames[key])

    def remove_item(self, key, value):
        del (self[key])[value.circuit]

    def remove_global_device(self, glob_dev_id):
        try:
            for devtype_name in num_to_devtype_name.values():
                to_delete = []
                for dev_name in self[devtype_name]:
                    if ((self[devtype_name])[dev_name]).dev_id == glob_dev_id:
                        to_delete += [(self[devtype_name])[dev_name]]
                for value in to_delete:
                    del (self[devtype_name])[value.circuit]
        except KeyError as E:
            logger.warning(f"Trying to remove non-existing global device ({E})")

    def by_int(self, devtype_name, circuit=None, major_group=None):
        circuit = str(circuit) if circuit is not None else None
        devdict = self[devtype_name]
        if circuit is None:
            if major_group is not None:
                outp = []
                if len(devdict.values()) > 1:
                    for single_dev in devdict.values():
                        if single_dev.major_group == major_group:
                            outp += [single_dev]
                    return outp
                elif len(devdict.values()) > 0:
                    single_dev = list(devdict.values())[0]
                    if single_dev.major_group == major_group:
                        return devdict.values()
                    else:
                        return []
                else:
                    return []
            else:
                return devdict.values()
        try:
            return devdict[circuit]
        except KeyError:
            if circuit in self.aliases:
                return self.aliases[circuit]
            else:
                raise DeviceNotFound(f"Invalid device circuit '{str(circuit)}' with devtypeid '{devtype_name}'")

    def by_name(self, devtype, circuit=None):
        try:
            devdict = self[devtype]
        except KeyError:
            devdict = self[self.altnames[devtype]]
        if circuit is None:
            return devdict.values()
        circuit = str(circuit)
        try:
            return devdict[circuit]
        except KeyError:
            if circuit not in self.aliases:
                raise Exception(f"Circuit or alias with name '{circuit}' not defined!")
            ret = self.aliases[circuit]
            ret_name = ret.devtype
            if ret_name == devtype or ret_name == devtype_altnames[devtype]:
                return ret
            else:
                raise Exception(f"Invalid device circuit '{str(circuit)}' with devtype '{devtype}'")

    def register_device(self, devtype_name, device):
        """ can be called with devtype = INTEGER or NAME
        """
        if devtype_name is None:
            raise Exception('Device type must contain INTEGER or NAME')
        devdict = self[devtype_name]

        devdict[str(device.circuit)] = device
        # assign saved alias
        for alias in self.aliases.get_aliases_by_circuit(devtype_name, str(device.circuit)):
            try:
                self.aliases.add(alias, device)
                device.alias = alias
                logger.info(f"Set alias {alias} to {devtype_name}[{device.circuit}]")
            except Exception as E:
                logger.warning(f"Error on setting saved alias: {str(E)}")

        devents.config(device)
        logger.debug(f"Registered new device '{devtype_name}' with circuit {device.circuit} \t ({device})")

    def set_alias(self, alias: str, device: Device, file_update: bool = False) -> None:
        try:
            if alias != device.alias:
                if alias == '' or alias is None:
                    if device.alias: self.aliases.delete(device.alias, file_update)
                    device.alias = alias
                    logger.debug(f"Reset alias of {device.devtype}[{device.circuit}]")
                elif alias != device.alias:
                    self.aliases.add(alias, device, file_update)
                    device.alias = alias
                    logger.debug(f"Set alias {alias} of {device.devtype}[{device.circuit}]")
        except Exception as E:
            logger.error(f"Error on setting alias {alias}: {str(E)}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            raise E


# # define device types constants
RO = "ro"
DO = "do"
DI = "di"
AI = "ai"
AO = "ao"
SENSOR = "sensor"
OWBUS = "owbus"
DS2408 = "ds2408"
MODBUS_SLAVE = "modbus_slave"
BOARD = "board"
LED = "led"
WATCHDOG = "watchdog"
REGISTER = "register"
DATA_POINT = "data_point"
TCPBUS = "tcp_bus"
SERIALBUS = "serial_bus"
DEVICE_INFO = "device_info"
OWPOWER = "owpower"
RUN = "run"
NV_SAVE = "nv_save"

# # corresponding device types names !! ORDER IS IMPORTANT
num_to_devtype_name = {
    0: 'ro',
    17: 'do',
    1: 'di',
    2: 'ai',
    3: 'ao',
    5: 'sensor',
    8: 'owbus',
    12: 'ds2408',
    15: 'modbus_slave',
    16: 'board',
    18: 'led',
    19: 'watchdog',
    20: 'register',
    24: 'data_point',
    26: 'tcp_bus',
    27: 'serial_bus',
    28: 'device_info',
    29: 'owpower',
    30: 'run',
    31: 'nv_save',
}

devtype_altnames = {
    'digitalinput': 'di',
    'input': 'di',
    'digitaloutput': 'do',
    'output': 'do',
    'relay': 'ro',
    'analoginput': 'ai',
    'analogoutput': 'ao',
    'wd': 'watchdog',
    'temp': 'sensor'
}

Devices = DeviceList(devtype_altnames)
for _key in num_to_devtype_name.values():
    Devices[_key] = {}

# define units
NONE = 0
CELSIUS = 1
VOLT = 2
AMPERE = 3
OHM = 4

unit_names = [
    '',
    'C',
    'V',
    'mA',
    'Ohm',
]

unit_altnames = {
    '': '',
    'C': 'Celsius',
    'V': 'Volt',
    'mA': 'miliampere',
    'Ohm': 'ohm'
}

