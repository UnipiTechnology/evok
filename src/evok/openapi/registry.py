"""The device types of the API: their response/params components and REST paths.

The OpenAPI document is generated from this registry plus the JSON schemas in
:mod:`evok.schemas` (the source of truth for the params and response shapes).
"""

from dataclasses import dataclass

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
        False,
        "",
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
