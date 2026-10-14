import json
from urllib.parse import urlencode

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.web

from evok.devices import AI, Devices, to_bool
from evok.evok import LegacyJsonHandler, LegacyRestHandler
from evok.w1 import OwBusDriver


@pytest.fixture
async def fetch():
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
    ]))
    server.add_sockets([sock])

    async def request(path, method='GET', body=None, headers=None):
        response = await tornado.httpclient.AsyncHTTPClient().fetch(
            f"http://127.0.0.1:{port}{path}", method=method, body=body, headers=headers, raise_error=False)
        return response.code, json.loads(response.body)
    yield request
    server.stop()


@pytest.fixture
def owbus(monkeypatch):
    bus = OwBusDriver('OWFS')
    Devices['owbus']['OWFS'] = bus
    calls = []
    monkeypatch.setattr(bus, 'do_scan', lambda: calls.append('scan'))

    async def do_reset():
        calls.append('reset')
    monkeypatch.setattr(bus, 'do_reset', do_reset)
    return calls


@pytest.mark.parametrize('form, expected', [
    ({'do_scan': '1'}, ['scan']),
    ({'do_scan': 'true'}, ['scan']),
    ({'do_scan': '0'}, []),
    ({'do_reset': '1'}, ['reset']),
    ({'do_reset': 'false'}, []),
])
async def test_owbus_flags_in_form(fetch, owbus, form, expected):
    code, reply = await fetch('/rest/owbus/OWFS', 'POST', urlencode(form))
    assert (code, reply['success']) == (200, True)
    assert owbus == expected


async def test_owbus_flags_in_json(fetch, owbus):
    code, _ = await fetch('/json/owbus/OWFS', 'POST', json.dumps({'do_scan': True, 'do_reset': False}))
    assert code == 200
    assert owbus == ['scan']


async def test_owbus_invalid_flag(fetch, owbus):
    code, _reply = await fetch('/rest/owbus/OWFS', 'POST', urlencode({'do_reset': 'maybe'}))
    assert code == 400
    assert owbus == []


@pytest.mark.parametrize('headers', [{'Content-Type': 'application/json'}, None])
async def test_rest_reads_json_body(fetch, owbus, headers):
    """ A JSON body to /rest was read as a form without fields and set nothing; without the header as curl -d """
    code, _ = await fetch('/rest/owbus/OWFS', 'POST', json.dumps({'do_scan': True}), headers)
    assert code == 200
    assert owbus == ['scan']


async def test_rest_json_body_is_validated(fetch, owbus):
    code, reply = await fetch('/rest/owbus/OWFS', 'POST', json.dumps({'do_reset': 'maybe'}),
                              {'Content-Type': 'application/json'})
    assert (code, reply['success']) == (400, False)
    assert owbus == []


async def test_rest_empty_body_sets_nothing(fetch, owbus):
    code, reply = await fetch('/rest/owbus/OWFS', 'POST', '')
    assert (code, reply['success']) == (200, True)
    assert owbus == []


@pytest.mark.parametrize('path', ['/rest/owbus/OWFS', '/json/owbus/OWFS'])
@pytest.mark.parametrize('body', ['[1]', '"do_scan"', 'not json'])
async def test_json_body_must_be_object(fetch, owbus, path, body):
    """ A JSON body which is not an object was a 500 (set(**list)) """
    code, reply = await fetch(path, 'POST', body, {'Content-Type': 'application/json'})
    assert code == 400 and set(reply['errors']) <= {'ValueError', 'JSONDecodeError'}, reply
    assert owbus == []


@pytest.mark.parametrize('value, expected', [
    (True, True), (False, False), (1, True), (0, False), ('1', True), ('0', False), ('True', True), ('', False)])
def test_to_bool(value, expected):
    assert to_bool(value) is expected


class FakeAnalog:
    def __init__(self, circuit, state):
        self.circuit = circuit
        self.state = {'dev': 'ai', 'circuit': circuit, **state}

    def full(self):
        return self.state


@pytest.fixture
def analogs():
    Devices[AI]['1_01'] = FakeAnalog('1_01', {'value': 1.0, 'range': [0, 10]})
    Devices[AI]['1_02'] = FakeAnalog('1_02', {'value': 2.0})         # no range in this mode


async def test_get_all_property(fetch, analogs):
    assert await fetch('/rest/ai/all/range') == (200, [{'circuit': '1_01', 'range': [0, 10]}])
    assert await fetch('/rest/ai/all/value') == (200, [{'circuit': '1_01', 'value': 1.0},
                                                       {'circuit': '1_02', 'value': 2.0}])


async def test_get_all_unknown_property(fetch, analogs):
    code, reply = await fetch('/rest/ai/all/foo')
    assert code == 404
    assert reply['errors'] == {'DeviceNotFound': 'Invalid property name foo'}


async def test_get_all(fetch, analogs):
    code, reply = await fetch('/rest/ai/all')
    assert code == 200
    assert [state['circuit'] for state in reply] == ['1_01', '1_02']


def test_get_all_includes_nv_save():
    from evok.devices import NV_SAVE
    from evok.handlers_base import EvokWebHandlerBase

    class NvSave:
        circuit = '1'

        def full(self):
            return {'dev': 'nv_save', 'circuit': '1', 'value': 0}
    Devices[NV_SAVE]['1'] = NvSave()
    assert EvokWebHandlerBase._get_all(None) == [{'dev': 'nv_save', 'circuit': '1', 'value': 0}]


class FakeOutput:
    devtype = 'do'

    def __init__(self, circuit):
        self.circuit = circuit
        self.alias = ''
        self.calls = []

    def full(self):
        return {'dev': 'do', 'circuit': self.circuit}

    async def set(self, **kw):
        self.calls.append(kw)


@pytest.mark.parametrize('path, code', [
    ('/rest/do/1_01', 200),
    ('/rest/do/1_01/', 200),
    ('/rest/do/1_01/alias', 200),
    ('/rest/do/1_01/value', 404),
    ('/rest/do/all', 404),
])
async def test_post_url(fetch, path, code):
    Devices['do']['1_01'] = FakeOutput('1_01')
    status, _reply = await fetch(path, 'POST', urlencode({'value': '1'}))
    assert status == code
    assert Devices['do']['1_01'].calls == ([{'value': '1'}] if code == 200 else [])


def test_alias_all_is_reserved():
    Devices['do']['1_01'] = FakeOutput('1_01')
    with pytest.raises(ValueError, match='reserved'):
        Devices.set_alias('all', Devices['do']['1_01'])


@pytest.fixture
def modbus_buses(l0306):
    """ An RTU bus with two units and a TCP bus with one, created from the configuration """
    from types import SimpleNamespace

    from evok import config
    config.create_devices(SimpleNamespace(get_comm_channels=lambda: {
        'RTU': {'type': 'MODBUSRTU', 'port': '/dev/null', 'baudrate': 9600, 'parity': 'E', 'retries': 2,
                'devices': {'u1': {'slave-id': 1, 'model': 'L0306'}, 'u2': {'slave-id': 2, 'model': 'L0306'}}},
        'TCP': {'type': 'MODBUSTCP', 'hostname': '192.168.1.10', 'devices': {'t1': {'slave-id': 3, 'model': 'L0306'}}},
    }), SimpleNamespace(definitions={'L0306': l0306}))


async def test_get_serial_bus(fetch, modbus_buses):
    """ #238: the bus had no full(), GET was 500 """
    code, reply = await fetch('/rest/serial_bus/RTU')
    assert code == 200
    assert reply == {'dev': 'serial_bus', 'circuit': 'RTU', 'port': '/dev/null', 'baudrate': 9600, 'parity': 'E',
                     'stopbits': 1, 'timeout': 0.5, 'retries': 2, 'probe_timeout': 0.1, 'devices': ['u1', 'u2']}


async def test_get_tcp_bus(fetch, modbus_buses):
    code, reply = await fetch('/json/tcp_bus/all')
    assert code == 200
    assert reply == [{'dev': 'tcp_bus', 'circuit': 'TCP', 'hostname': '192.168.1.10', 'port': 502, 'timeout': 0.5,
                      'connect_timeout': 1.0, 'retries': 1, 'probe_timeout': 0.5, 'devices': ['t1']}]


async def test_bus_cannot_be_set(fetch, modbus_buses):
    code, reply = await fetch('/rest/serial_bus/RTU', 'POST', urlencode({'baudrate': 19200}))
    assert (code, reply['success']) == (400, False)
    assert Devices.by_name('serial_bus', 'RTU').full()['baudrate'] == 9600


def test_get_all_skips_the_buses(modbus_buses):
    from evok.handlers_base import EvokWebHandlerBase
    assert not {'serial_bus', 'tcp_bus'} & {state['dev'] for state in EvokWebHandlerBase._get_all(None)}
