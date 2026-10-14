"""The response schemas of evok.schemas describe the full() of every device type.

full() is imperative, so a field added, renamed or dropped in a device without the
matching response schema would silently drift from the generated OpenAPI document
and from the black-box integration tests. This guard runs full() on a
representative device of every device type and checks the schema knows every key
it emits and requires only keys it emits.
"""

import jsonschema
import pytest

from evok import devices, schemas
from evok.blocks import SequencerDevice
from evok.config import DeviceInfo, SerialBusDevice, TcpBusDevice
from evok.devices import Aliases
from evok.modbus.analog import AnalogInput, AnalogOutput, DataPoint, OwTemperature, Register
from evok.modbus.digital import ULED, DigitalInput, DigitalOutput, Relay
from evok.modbus.scanner import ModbusScanner
from evok.modbus.special import NvSave, OwPower, Watchdog
from evok.openapi import build_openapi
from evok.openapi.__main__ import render
from evok.openapi.registry import DEVICES, INTERNAL_DEVTYPES, RESPONSE_DEVTYPES
from evok.w1 import DS18B20, DS2408, DS2438, OwBusDriver


class _FakeCache:
    scan_error = None


class _FakeClient:
    """The subset of Client used by full()"""

    def __init__(self):
        self.cache = _FakeCache()

    def comm(self):
        return "ok"

    def last_comm(self):
        return 0.0


def _scanner(client) -> ModbusScanner:
    """A Modbus unit without its transport, enough for full()"""
    scanner = ModbusScanner.__new__(ModbusScanner)
    scanner.client = client
    scanner.cache = client.cache
    scanner.circuit = "1"
    scanner.modbus_address = 1
    scanner.modbus_type = "TCP"
    scanner.modbus_spec = "127.0.0.1"
    scanner.scan_interval = 1.0
    scanner.scan_enabled = True
    scanner.alias = ""
    return scanner


AI_MODES = {
    "Voltage": {"value": 0, "unit": "V", "range": [0, 10]},
    "Current": {"value": 1, "unit": "mA", "range": [0, 20]},
}


def _with(device, **attributes):
    """ The device with the attributes of a scanned state, e.g. a value which is not a number """
    for name, value in attributes.items():
        setattr(device, name, value)
    return device


def samples() -> dict[str, list]:
    """One representative device of every device type of the response schemas"""
    client = _FakeClient()
    bus = OwBusDriver("OW")
    do = DigitalOutput("1_01", client, 0, 0, 1, modes=["Simple", "PWM"])
    temp = DS18B20("28.000001", "DS18B20", bus)
    by_dev = {
        "di": [DigitalInput("1_01", client, 0, 1)],
        "do": [do],
        "ro": [Relay("1_01", client, 0, 0, 1)],
        "led": [ULED("1_01", client, 0, 0, 1)],
        "ai": [AnalogInput("1_01", client, 0), _with(AnalogInput("1_02", client, 0, modes=AI_MODES), value="NaN")],
        "ao": [AnalogOutput("1_01", client, 0), AnalogOutput("1_02", client, 0, modes=AI_MODES)],
        "wd": [Watchdog("1", client, 0, 1, 2)],
        "register": [Register("1_01", client, 0)],
        "data_point": [
            DataPoint("1_01", client, 0, datatype="uint16", writable=True),
            OwTemperature("1_02", client, 0, 1, 1, datatype="int16", name="temperature", unit="C"),
        ],
        "owpower": [OwPower("1", client, 0)],
        "nv_save": [NvSave("1", client, 0)],
        "owbus": [OwBusDriver("OWBUS")],
        "temp": [temp],
        "1wdevice": [DS2408("29.000001", "DS2408", bus), DS2438("26.000001", "DS2438", bus)],
        "modbus_slave": [_scanner(client)],
        "device_info": [DeviceInfo("1", "Neuron", "M103", 0, 2)],
        "serial_bus": [
            SerialBusDevice("S", object(), port="/dev/ttyNS0", baudrate=19200, parity="N", stopbits=1, timeout=0.5,
                            retries=0, probe_timeout=0.1)
        ],
        "tcp_bus": [TcpBusDevice("T", object(), hostname="127.0.0.1", port=502, timeout=1.0, connect_timeout=2.0,
                                 retries=0, probe_timeout=1.0)],
        "sequencer": [SequencerDevice(do)],
        "run": [Aliases({})],
    }
    by_dev["watchdog"] = by_dev["wd"]
    by_dev["sensor"] = by_dev["temp"]
    return by_dev


def test_samples_cover_every_response_schema():
    """Every response schema is exercised below (a new device type cannot be skipped silently)"""
    assert set(samples()) == set(schemas.responses)


@pytest.mark.parametrize("dev", sorted(schemas.responses))
def test_response_schema_matches_full(dev):
    schema = schemas.responses[dev]
    properties = set(schema["properties"])
    required = set(schema.get("required", []))
    for device in samples()[dev]:
        state = device.full()
        unknown = set(state) - properties
        assert not unknown, (
            f"{dev} ({type(device).__name__}): full() emits {sorted(unknown)} "
            f"which the response schema does not declare"
        )
        missing = required - set(state)
        assert not missing, f"{dev} ({type(device).__name__}): full() does not emit the required {sorted(missing)}"


@pytest.mark.parametrize("dev", sorted(schemas.responses))
def test_full_is_valid_by_the_response_schema(dev):
    """ The types of the values, also of a device before its first scan (null) and of a value which is not a number """
    for device in samples()[dev]:
        jsonschema.validate(device.full(), schemas.responses[dev])


# The devtype list is not duplicated: RESPONSE_DEVTYPES in the registry is the single
# link between the runtime devtypes (evok.devices) and the generated document. These
# checks make a new or renamed devtype fail loudly instead of dropping out of the OAS.


def test_response_schemas_cover_the_api_devtypes():
    """Every response schema is a known API device type and vice versa"""
    assert set(schemas.responses) == set(RESPONSE_DEVTYPES)


def test_every_runtime_devtype_is_exposed_or_internal():
    """Every runtime devtype is either in the API or listed as internal"""
    runtime = set(devices.num_to_devtype_name.values())
    assert runtime == set(RESPONSE_DEVTYPES.values()) | set(INTERNAL_DEVTYPES)


def test_registry_devs_are_api_devtypes():
    """Every device type of a REST path is a known API device type"""
    assert {device.dev for device in DEVICES} <= set(RESPONSE_DEVTYPES)


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            else:
                yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


def test_every_ref_of_the_document_exists():
    """ A reference to a missing component breaks the document """
    document = build_openapi()
    for ref in set(_refs(document)):
        node = document
        for part in ref.removeprefix("#/").split("/"):
            assert part in node, f"{ref} does not exist"
            node = node[part]


def test_the_document_has_no_yaml_aliases():
    """ The shared schemas are written in full, some tools do not read the anchors and aliases of YAML """
    text = render()
    assert "&id" not in text and "*id" not in text
