"""The device types of the API: their response/params components and REST paths.

The OpenAPI document is generated from this registry plus the JSON schemas in
:mod:`evok.schemas` (the source of truth for the params and response shapes).
"""

from dataclasses import dataclass, replace

from .. import devices


@dataclass(frozen=True)
class DeviceType:
    """One device type of the REST/JSON API."""

    dev: str  # the value of the `dev` field of the response
    segment: str  # the segment of the device in the path, e.g. /rest/do/1_01
    component: str  # the name of the response schema in components.schemas
    tag: str  # the tag of the operations
    response: str  # the key in evok.schemas.responses
    input: str | None = None  # the key in evok.schemas.schemas, None if read-only
    settable: bool = False
    gettable: bool = True
    summary_get: str = ""
    summary_post: str = ""
    # the other shapes of the state on the same path: (component, the key in evok.schemas.responses)
    alternatives: tuple[tuple[str, str], ...] = ()
    sequenced: bool = False  # an output of a sequencer, a POST is refused while its sequence runs (409)
    description: str = ""
    get_description: str = ""
    post_description: str = ""


DEVICES: list[DeviceType] = [
    DeviceType(
        "di",
        "di",
        "Digital_input",
        "Digital input",
        "di",
        "di",
        True,
        True,
        "Read digital input",
        "Set digital input properties",
    ),
    DeviceType(
        "do",
        "do",
        "Digital_output",
        "Digital output",
        "do",
        "do",
        True,
        True,
        "Read digital output",
        "Set output properties",
        sequenced=True,
    ),
    DeviceType(
        "ro",
        "ro",
        "Relay_output",
        "Relay output",
        "ro",
        "ro",
        True,
        True,
        "Read relay output",
        "Set relay value",
        sequenced=True,
    ),
    DeviceType(
        "led", "led", "Led", "User LED", "led", "led", True, True, "Read user LED", "Set LED properties", sequenced=True
    ),
    DeviceType(
        "ai", "ai", "Analog_input", "Analog input", "ai", "ai", True, True, "Read analog input", "Set analog input mode"
    ),
    DeviceType(
        "ao",
        "ao",
        "Analog_output",
        "Analog output",
        "ao",
        "ao",
        True,
        True,
        "Read analog output",
        "Set analog output value",
    ),
    DeviceType(
        "wd",
        "wd",
        "Watchdog",
        "Master watchdog",
        "wd",
        "wd",
        True,
        True,
        "Read master watchdog",
        "Set watchdog properties",
    ),
    DeviceType(
        "owpower",
        "owpower",
        "Owpower",
        "1-Wire bus",
        "owpower",
        "owpower",
        True,
        True,
        "Read 1-Wire power supply",
        "Set 1-Wire power supply",
    ),
    DeviceType(
        "owbus",
        "owbus",
        "Owbus",
        "1-Wire bus",
        "owbus",
        "owbus",
        True,
        True,
        "Read 1-Wire bus",
        "Set 1-Wire bus properties",
    ),
    DeviceType(
        "temp",
        "temp",
        "Temp",
        "1-Wire bus",
        "temp",
        "1wdevice",
        True,
        True,
        "Read 1-Wire sensor",
        "Set 1-Wire sensor interval",
        alternatives=(("Onewire_device", "1wdevice"),),
        description="The 1-Wire sensors: a thermometer (dev *temp*) or another 1-Wire device (dev *1wdevice*, "
        "DS2438, DS2408, DS2406, DS2413). The device types *sensor* and *1wdevice* are other names of the path.",
    ),
    DeviceType(
        "nv_save",
        "nv_save",
        "NvSave",
        "Non-volatile memory",
        "nv_save",
        "nv_save",
        True,
        True,
        "Read the saving to the non-volatile memory",
        "Save settings to the non-volatile memory",
    ),
    DeviceType(
        "register",
        "register",
        "Modbus_register",
        "Modbus register",
        "register",
        "register",
        True,
        True,
        "Read Modbus register",
        "Write Modbus register",
    ),
    DeviceType(
        "data_point",
        "data_point",
        "Data_point",
        "Data point",
        "data_point",
        "data_point",
        True,
        True,
        "Read data point",
        "Write data point",
    ),
    DeviceType(
        "sequencer",
        "sequencer",
        "Sequencer",
        "Sequencer",
        "sequencer",
        "sequencer",
        True,
        True,
        "Read the sequencer of an output",
        "Start a pulse or a sequence of an output",
    ),
    DeviceType(
        "modbus_slave",
        "modbus_slave",
        "Modbus_slave",
        "Modbus slave",
        "modbus_slave",
        "modbus_slave",
        True,
        True,
        "Read Modbus unit",
        "Set Modbus unit properties",
    ),
    DeviceType(
        "device_info",
        "device_info",
        "Device_info",
        "Device info",
        "device_info",
        None,
        False,
        True,
        "Read device info",
        "",
    ),
    DeviceType(
        "serial_bus",
        "serial_bus",
        "Serial_bus",
        "Modbus bus",
        "serial_bus",
        None,
        False,
        True,
        "Read the Modbus RTU bus",
        "",
    ),
    DeviceType(
        "tcp_bus", "tcp_bus", "Tcp_bus", "Modbus bus", "tcp_bus", None, False, True, "Read the Modbus TCP bus", ""
    ),
]


_ALL = " With the circuit *all* the states of all devices of the type."
_SET = " The state after the change is returned. The params are validated by the schema, an unknown param is refused."

# the descriptions of the operations by the segment of the path: (GET, POST)
_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "di": ("The state of a digital input, its value, counter and debounce." + _ALL,
           "Set the debounce, the counter or the mode of a digital input." + _SET),
    "do": ("The state of a digital output, its value and PWM." + _ALL,
           "Set the value or the PWM of a digital output; refused with 409 while its sequencer runs." + _SET),
    "ro": ("The state of a relay output." + _ALL,
           "Set the value of a relay output; refused with 409 while its sequencer runs." + _SET),
    "led": ("The state of a user LED." + _ALL,
            "Set the value of a user LED; refused with 409 while its sequencer runs." + _SET),
    "ai": ("The state of an analog input, its value in the unit of its mode." + _ALL,
           "Set the mode of an analog input." + _SET),
    "ao": ("The state of an analog output, its value in the unit of its mode." + _ALL,
           "Set the value or the mode of an analog output." + _SET),
    "wd": ("The state of the master watchdog of a Modbus unit." + _ALL,
           "Enable or disable the master watchdog, set its timeout or restart the unit." + _SET),
    "owpower": ("The power of a 1-Wire bus." + _ALL, "Switch the power of a 1-Wire bus." + _SET),
    "owbus": ("The state of a 1-Wire bus read by the kernel." + _ALL,
              "Set the intervals of a 1-Wire bus, start a search or reset its master." + _SET),
    "temp": ("The state of a 1-Wire sensor." + _ALL, "Set the interval of the reads of a 1-Wire sensor." + _SET),
    "nv_save": ("The saving to the non-volatile memory of a Modbus unit, value 1 for 2 s after a save." + _ALL,
                "Save the settings of a Modbus unit to its non-volatile memory, the unit loads them after its "
                "restart." + _SET),
    "register": ("The raw value of a Modbus register of a custom Modbus device." + _ALL,
                 "Write the raw value of a Modbus register." + _SET),
    "data_point": ("The value of a data point of a Modbus unit." + _ALL,
                   "Write the value of a data point; only a data point with `writable: true` in its HW definition "
                   "in a holding register can be written, the value is converted to the register by the inverse of "
                   "its transformation, `(value - offset) / factor`." + _SET),
    "sequencer": ("The running pulse or sequence of an output (RO, DO, LED), the circuit is the type and the circuit "
                  "of the output, e.g. `do_1_01`." + _ALL,
                  "Start a pulse or a sequence of an output, or cancel it." + _SET),
    "modbus_slave": ("The state of a Modbus unit and its scan." + _ALL,
                     "Enable or disable the periodic scan of a Modbus unit." + _SET),
    "device_info": ("The description of the controller or a unit." + _ALL, ""),
    "serial_bus": ("The configuration and the Modbus units of a Modbus RTU bus, it cannot be set." + _ALL, ""),
    "tcp_bus": ("The configuration and the Modbus units of a Modbus TCP bus, it cannot be set." + _ALL, ""),
}
DEVICES = [replace(device, get_description=_DESCRIPTIONS[device.segment][0],
                   post_description=_DESCRIPTIONS[device.segment][1]) for device in DEVICES]


# The runtime device type (evok.devices) of every response schema key. The API name
# differs for a few of them (wd/watchdog, temp/sensor/1wdevice) and 'run' is not a
# device path of its own. This is the single link between the runtime devtypes and the
# API; tests/test_openapi.py checks it both ways, so a new devtype cannot silently drop
# out of the generated document.
RESPONSE_DEVTYPES: dict[str, str] = {
    "di": devices.DI,
    "do": devices.DO,
    "ro": devices.RO,
    "led": devices.LED,
    "ai": devices.AI,
    "ao": devices.AO,
    "wd": devices.WATCHDOG,
    "watchdog": devices.WATCHDOG,
    "owpower": devices.OWPOWER,
    "owbus": devices.OWBUS,
    "temp": devices.SENSOR,
    "sensor": devices.SENSOR,
    "1wdevice": devices.SENSOR,
    "nv_save": devices.NV_SAVE,
    "register": devices.REGISTER,
    "data_point": devices.DATA_POINT,
    "sequencer": devices.SEQUENCER,
    "modbus_slave": devices.MODBUS_SLAVE,
    "device_info": devices.DEVICE_INFO,
    "serial_bus": devices.SERIALBUS,
    "tcp_bus": devices.TCPBUS,
    "run": devices.RUN,
}

# The device types of evok.devices which are not exposed over the REST/JSON API
INTERNAL_DEVTYPES: frozenset[str] = frozenset({devices.DS2408, "board"})


def by_segment() -> dict[str, DeviceType]:
    return {device.segment: device for device in DEVICES}
