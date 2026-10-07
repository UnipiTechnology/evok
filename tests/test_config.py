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


def write_config(tmp_path, config_text, autogen_text=None):
    (tmp_path / 'config.yaml').write_text(config_text)
    if autogen_text is not None:
        (tmp_path / 'autogen.yaml').write_text(autogen_text)
    return config.EvokConfig(str(tmp_path))


def test_config_with_autogen(tmp_path):
    conf = write_config(tmp_path, 'autogen: true\napis:\n  port: 8081\n',
                        'apis:\n  port: 8080\n  address: ""\ncomm_channels:\n  LOCAL_TCP: {type: MODBUSTCP}\n')
    assert conf.apis == {'port': 8081, 'address': ''}     # config.yaml overrides autogen.yaml
    assert list(conf.comm_channels) == ['LOCAL_TCP']


def test_config_python_tags_are_not_executed(tmp_path):
    with pytest.raises(Exception):
        write_config(tmp_path, 'apis: !!python/object/apply:os.getcwd []\n')


@pytest.mark.parametrize('autogen_text', ['', '# only a comment\n'])
def test_empty_autogen_is_skipped(tmp_path, caplog, autogen_text):
    conf = write_config(tmp_path, 'autogen: true\napis:\n  port: 8081\n', autogen_text)
    assert conf.apis == {'port': 8081}
    assert 'is empty' in caplog.text


def test_empty_sections(tmp_path):
    conf = write_config(tmp_path, 'apis:\nlogging:\ncomm_channels:\n')
    assert (conf.apis, conf.logging, conf.comm_channels) == ({}, {}, {})


def test_config_not_a_mapping(tmp_path):
    with pytest.raises(config.EvokConfigError):
        write_config(tmp_path, '- a list\n')


def test_error_in_bus_does_not_stop_other_buses(caplog):
    create({
        'RTU': {'type': 'MODBUSRTU'},                   # missing port
        'EMPTY': None,                                  # empty section
        'NOTYPE': {'interval': 10},
        'OWFS': {'type': 'OWFS', 'devices': {'empty': None, 'temp1': {'type': 'DS18B20', 'address': '28.0000AB'}}},
    })
    assert list(Devices[OWBUS]) == ['OWFS']
    assert list(Devices[SENSOR]) == ['temp1']
    assert "Error in config of bus 'RTU'" in caplog.text
    assert "Unknown type 'None' of bus 'EMPTY'" in caplog.text
    assert "Unknown type 'None' of bus 'NOTYPE'" in caplog.text
