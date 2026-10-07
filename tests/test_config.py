from types import SimpleNamespace

import pytest

from evok import config
from evok.devices import Devices, OWBUS, SENSOR
from evok.owdevice import DS18B20, OwBusDriver


@pytest.mark.parametrize('text', [
    'version: 2.0\naliases:\n  kitchen: {devtype: di, circuit: "1_01"}\n',       # a number without quotes
    'version: "2.0"\naliases:\n  kitchen: {devtype: di, circuit: "1_01"}\n',
    'aliases:\n  kitchen: {devtype: di, circuit: "1_01"}\n',                      # no version, a dict
    'version: 1.0\naliases:\n  - {name: kitchen, dev_type: di, circuit: "1_01"}\n',
    'aliases:\n  - {name: kitchen, dev_type: di, circuit: "1_01"}\n',             # no version, a list
])
def test_load_aliases(tmp_path, text):
    path = tmp_path / 'alias.yaml'
    path.write_text(text)
    config.load_aliases(str(path))
    assert Devices.aliases.initial_dict == {'kitchen': {'devtype': 'di', 'circuit': '1_01'}}


def test_load_aliases_unknown_version(tmp_path, caplog):
    path = tmp_path / 'alias.yaml'
    path.write_text('version: 3.0\naliases:\n  kitchen: {devtype: di, circuit: "1_01"}\n')
    config.load_aliases(str(path))
    assert Devices.aliases.initial_dict == {}
    assert "Unknown version '3.0'" in caplog.text


def create(comm_channels):
    config.create_devices(SimpleNamespace(get_comm_channels=lambda: comm_channels), SimpleNamespace(definitions={}))


def test_owfs_bus_with_sensors(caplog):
    create({'OWFS': {'type': 'OWFS', 'interval': 10, 'devices': {
        'temp1': {'type': 'DS18B20', 'address': '28.0000AB', 'interval': '30'},
        'foo': {'type': 'DS9999', 'address': '99.000001'},
        'noaddr': {'type': 'DS18B20'},
    }}})
    bus = Devices[OWBUS]['OWFS']
    assert isinstance(bus, OwBusDriver)
    sensor = Devices[SENSOR]['temp1']
    assert isinstance(sensor, DS18B20)
    assert (sensor.address, sensor.interval) == ('28.0000AB', 30)
    assert bus.mysensors == [sensor]
    assert list(Devices[SENSOR]) == ['temp1']
    assert "Unsupported type 'DS9999'" in caplog.text
    assert "Missing 'address'" in caplog.text


def test_unknown_bus_type(caplog):
    create({'OW': {'type': 'OWBUS', 'devices': {'temp1': {'type': 'DS18B20', 'address': '28.0000AB'}}}})
    assert list(Devices[OWBUS]) == []
    assert list(Devices[SENSOR]) == []
    assert "Unknown type 'OWBUS' of bus 'OW'" in caplog.text
