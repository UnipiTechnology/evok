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

    def __init__(self, initial_dict: dict[str, dict[str, str]]):
        self.devtype = 'run'
        self.circuit = 'alias'
        self.alias_dict: dict[str, Device] = {}
        self.initial_dict: dict[str, dict[str, str]] = {}
        for key, value in initial_dict.items():
            if not isinstance(value, dict):
                logger.warning(f"Aliases: Invalid record of alias '{key}', skipped")
                continue
            devtype = value.get('devtype')
            if devtype is None:
                # kept in the file, but it is never assigned to a device
                logger.warning(f"Aliases: Missing devtype of alias '{key}'")
            elif isinstance(devtype, int) or (isinstance(devtype, str) and devtype.isdigit()):
                name = num_to_devtype_name.get(int(devtype))
                if name is None:
                    logger.warning(f"Aliases: Unknown devtype {devtype} of alias '{key}'")
                else:
                    value['devtype'] = name
                    logger.warning(f"Aliases: Detected old devtype '{key}'! Upgrading...")
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

    def validate(self, alias: str, device: Device) -> None:
        # check duplicity
        if alias in self.alias_dict:
            raise ValueError(f"Duplicate alias {alias}")
        # an alias loaded from the file belongs to its device, even when the device is not registered yet
        rec = self.initial_dict.get(alias)
        if rec is not None and (rec.get('devtype') != device.devtype or rec.get('circuit') != str(device.circuit)):
            raise ValueError(f"Alias {alias} belongs to {rec.get('devtype')} {rec.get('circuit')}")
        # check alias name
        if not re.fullmatch(r"[A-Za-z0-9._-]+", alias):
            raise ValueError(f"Invalid alias {alias}")
        # GET /rest/<dev>/all returns all devices of the type, such alias would never be used
        if alias == 'all':
            raise ValueError("Alias all is reserved")

    def add(self, alias: str, device: Device, file_update: bool = False):
        if alias != device.alias:
            self.validate(alias, device)
        # delete old alias
        if device.alias:
            self.delete(device.alias)
        # delete alias from initial_dict
        if alias:
            self.delete(alias)
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

    def remove(self, alias: str) -> None:
        """ Delete an alias of a registered device or an alias loaded from the file """
        if alias not in self.alias_dict and alias not in self.initial_dict:
            raise ValueError(f"Unknown alias {alias}")
        device = self.alias_dict.get(alias)
        if device is not None:
            device.alias = ''
        self.delete(alias)

    def get_aliases_by_circuit(self, devtype: str, circuit: str):
        return list((alias for alias, rec in self.initial_dict.items()
                     if (rec.get("devtype", None) == devtype) and (rec.get("circuit", None) == circuit)))

    def get_dict_to_save(self) -> dict[str, dict[str, str]]:
        aliases = deepcopy(self.initial_dict)
        aliases.update(dict(((alias, {"circuit": device.circuit, "devtype": device.devtype})
                             for alias, device in self.alias_dict.items())))
        return aliases

    @property
    def aliases(self) -> dict:
        return {k: {"circuit": f"{v.devtype}_{v.circuit}",
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

    async def set(self, save: bool = False, delete: str = None):
        if delete is not None:
            self.remove(delete)
        if save is not None and bool(int(save)):
            self.set_force_save()


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

    def _devdict(self, devtype):
        """ Devices of a type, the type can be an altname """
        try:
            return self[devtype]
        except KeyError:
            raise DeviceNotFound(f"Invalid device type '{devtype}'")

    def by_name(self, devtype, circuit=None, major_group=None):
        """ The device of a type (or its altname) with a circuit or an alias,
            without a circuit all devices of the type, optionally of a major_group
        """
        devdict = self._devdict(devtype)
        if circuit is None:
            if major_group is not None:
                return [dev for dev in devdict.values() if dev.major_group == major_group]
            return devdict.values()
        circuit = str(circuit)
        try:
            return devdict[circuit]
        except KeyError:
            if circuit not in self.aliases:
                raise DeviceNotFound(f"Circuit or alias with name '{circuit}' not defined!")
            ret = self.aliases[circuit]
            ret_name = ret.devtype
            if ret_name == devtype or ret_name == devtype_altnames.get(devtype):
                return ret
            else:
                raise DeviceNotFound(f"Invalid device circuit '{str(circuit)}' with devtype '{devtype}'")

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

    def set_alias(self, alias: str | None, device: Device, file_update: bool = False) -> None:
        """ Set or reset ('' or None) the alias, an invalid alias raises ValueError logged by the caller """
        if alias == device.alias:
            return
        if alias == '' or alias is None:
            if device.alias:
                self.aliases.delete(device.alias, file_update)
            # no alias is '', full() of the devices tests it
            device.alias = ''
            logger.debug(f"Reset alias of {device.devtype}[{device.circuit}]")
        else:
            # by_name() finds the circuit first, such alias would never be used
            if alias in self[device.devtype]:
                raise ValueError(f"Alias {alias} is a circuit of {device.devtype}")
            self.aliases.add(alias, device, file_update)
            device.alias = alias
            logger.debug(f"Set alias {alias} of {device.devtype}[{device.circuit}]")


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
    'temp': 'sensor',
    '1wdevice': 'sensor',
}


def devtype_of(name: str) -> str:
    """ Device type of a name, also of 'dev' in full() which is not always the device type (e.g. 'wd') """
    return devtype_altnames.get(name, name)

Devices = DeviceList(devtype_altnames)
for _key in num_to_devtype_name.values():
    Devices[_key] = {}
