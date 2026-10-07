import json
from urllib.parse import urlencode

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.web

from evok.devices import Devices, AI
from evok.evok import LegacyJsonHandler, LegacyRestHandler
from evok.owdevice import OwBusDriver, to_bool


@pytest.fixture
async def fetch():
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
    ]))
    server.add_sockets([sock])

    async def request(path, method='GET', body=None):
        response = await tornado.httpclient.AsyncHTTPClient().fetch(
            f"http://127.0.0.1:{port}{path}", method=method, body=body, raise_error=False)
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
    code, reply = await fetch('/rest/owbus/OWFS', 'POST', urlencode({'do_reset': 'maybe'}))
    assert code == 400
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
