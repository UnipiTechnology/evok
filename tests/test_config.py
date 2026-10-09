import asyncio
import struct
import time
from types import SimpleNamespace

import pytest
from tmodbus import AsyncModbusClient, AsyncSmartTransport
from tmodbus.exceptions import CRCError, ModbusConnectionError, RequestRetryFailedError, ServerDeviceBusyError

from evok import config
from evok.devices import Devices, OWBUS, SENSOR, SERIALBUS, TCPBUS
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


@pytest.mark.parametrize('bus, expected', [
    ({'type': 'MODBUSTCP'}, {'timeout': 0.5, 'connect_timeout': 1.0}),
    ({'type': 'MODBUSTCP', 'timeout': 2, 'connect_timeout': '3.5'}, {'timeout': 2.0, 'connect_timeout': 3.5}),
    ({'type': 'MODBUSRTU', 'port': '/dev/null'}, {'timeout': 0.5}),
    ({'type': 'MODBUSRTU', 'port': '/dev/null', 'timeout': 1.5}, {'timeout': 1.5}),
])
def test_modbus_timeouts(bus, expected):
    create({'BUS': bus})
    devtype = TCPBUS if bus['type'] == 'MODBUSTCP' else SERIALBUS
    transport = Devices[devtype]['BUS'].bus_driver.base_transport
    assert {key: getattr(transport, key) for key in expected} == expected


@pytest.mark.parametrize('bus, attempts', [
    ({'type': 'MODBUSTCP'}, 2),
    ({'type': 'MODBUSTCP', 'retries': 0}, 1),
    ({'type': 'MODBUSRTU', 'port': '/dev/null', 'retries': 3}, 4),
])
def test_modbus_retries(bus, attempts):
    create({'BUS': bus})
    devtype = TCPBUS if bus['type'] == 'MODBUSTCP' else SERIALBUS
    stop = Devices[devtype]['BUS'].bus_driver.response_retry_strategy.stop
    assert [s.max_attempt_number for s in stop.stops if hasattr(s, 'max_attempt_number')] == [attempts]


async def test_modbus_tcp_is_opened_by_the_first_request():
    """ The bus was opened by a task of Evok, its failure was not reported, auto_reconnect opens it """
    async def unit(reader, writer):
        # a Modbus TCP unit, read holding registers returns 42
        while True:
            header = await reader.readexactly(7)
            tid, _, length, unit_id = struct.unpack('>HHHB', header)
            pdu = await reader.readexactly(length - 1)
            response = bytes([pdu[0], 2]) + struct.pack('>H', 42)
            writer.write(struct.pack('>HHHB', tid, 0, len(response) + 1, unit_id) + response)
            await writer.drain()

    server = await asyncio.start_server(unit, '127.0.0.1', 0)
    try:
        create({'BUS': {'type': 'MODBUSTCP', 'port': server.sockets[0].getsockname()[1]}})
        client = AsyncModbusClient(Devices[TCPBUS]['BUS'].bus_driver, unit_id=1)
        assert await client.read_holding_registers(0, quantity=1) == [42]
    finally:
        server.close()


def test_modbus_invalid_retries_skips_the_bus(caplog):
    create({'BUS': {'type': 'MODBUSTCP', 'retries': -1}})
    assert 'BUS' not in Devices[TCPBUS]
    assert "Error in config of bus 'BUS'" in caplog.text


def test_hw_dict(tmp_path, caplog):
    (tmp_path / 'xS51.yaml').write_text('type: xS51\n')
    (tmp_path / 'my.yaml.yaml').write_text('type: my\n')
    (tmp_path / 'broken.yaml').write_text('type: [\n')
    (tmp_path / 'list.yaml').write_text('- a\n')
    (tmp_path / 'empty.yaml').write_text('')
    (tmp_path / 'notes.txt').write_text('type: notes\n')
    hw = config.HWDict(dir_paths=[str(tmp_path)])                 # no trailing slash
    assert hw.definitions == {'xS51': {'type': 'xS51'}, 'my.yaml': {'type': 'my'}}
    assert "Cannot load definition file" in caplog.text
    assert "does not contain a mapping" in caplog.text


@pytest.mark.parametrize('name', ['alias.yaml', 'alias.yml', 'aliases'])
def test_load_aliases_any_extension(tmp_path, name):
    path = tmp_path / name
    path.write_text('version: "2.0"\naliases:\n  kitchen: {devtype: di, circuit: "1_01"}\n')
    config.load_aliases(str(path))
    assert list(Devices.aliases.initial_dict) == ['kitchen']


@pytest.mark.parametrize('text', [None, '', 'aliases: [\n', '- a\n'])
def test_load_aliases_invalid_file(tmp_path, text):
    path = tmp_path / 'alias.yaml'
    if text is not None:
        path.write_text(text)
    config.load_aliases(str(path))
    assert Devices.aliases.initial_dict == {}


class FakeTransport:
    """ The base transport of AsyncSmartTransport, the results of open() and send_and_receive() are given """

    def __init__(self, open_errors=(), responses=()):
        self.open_errors = list(open_errors)
        self.responses = list(responses)
        self.opened = False
        self.opens = 0
        self.requests = 0

    def is_open(self):
        return self.opened

    async def open(self):
        self.opens += 1
        error = self.open_errors.pop(0) if self.open_errors else None
        if error is not None:
            raise error
        self.opened = True

    async def close(self):
        self.opened = False

    async def send_and_receive(self, unit_id, pdu):
        self.requests += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def smart_transport(base, retries=1):
    return AsyncSmartTransport(base, wait_between_requests=0.0, wait_after_connect=0.0,
                               retry_on_device_busy=True, retry_on_device_failure=False,
                               **config.retry_strategies(0.1, 0.1, retries))


async def test_unavailable_unit_fails_fast():
    """ The default retries of tmodbus locked the bus up to 60 s for each request """
    base = FakeTransport(open_errors=[ModbusConnectionError('refused')] * 10)
    start = time.monotonic()
    with pytest.raises(RequestRetryFailedError):
        await smart_transport(base).send_and_receive(1, 'pdu')
    assert time.monotonic() - start < 1
    assert (base.opens, base.requests) == (2, 0)              # one reconnect for each of two attempts


async def test_lost_connection_is_reconnected():
    base = FakeTransport(responses=[ModbusConnectionError('reset'), 'response'])
    base.opened = True
    assert await smart_transport(base).send_and_receive(1, 'pdu') == 'response'
    assert (base.opens, base.requests) == (1, 2)


@pytest.mark.parametrize('error', [CRCError('noise', response_bytes=b'\x01'), TimeoutError('no response')])
async def test_other_errors_are_not_retried(error):
    base = FakeTransport(responses=[error, 'response'])
    base.opened = True
    with pytest.raises(type(error)):
        await smart_transport(base).send_and_receive(1, 'pdu')
    assert base.requests == 1


@pytest.mark.parametrize('retries, requests', [(0, 1), (1, 2), (3, 4)])
async def test_retries_of_busy_unit_are_configured(retries, requests):
    base = FakeTransport(responses=[ServerDeviceBusyError(0x03)] * 5)
    base.opened = True
    with pytest.raises(RequestRetryFailedError):
        await smart_transport(base, retries).send_and_receive(1, 'pdu')
    assert base.requests == requests


@pytest.mark.parametrize('bus_data, retries', [({}, 1), ({'retries': 0}, 0), ({'retries': 3}, 3)])
def test_bus_retries(bus_data, retries):
    assert config.bus_retries(bus_data) == retries


@pytest.mark.parametrize('value', [-1, 1.5, '2', True, None])
def test_bus_retries_invalid(value):
    with pytest.raises(ValueError, match='retries'):
        config.bus_retries({'retries': value})
