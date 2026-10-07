import asyncio
import json

import pytest
import tornado.httpserver
import tornado.testing
import tornado.web
import tornado.websocket

from evok.devices import Devices, DI, DO
from evok.ws_handler import WsHandler


class FakeDevice:
    def __init__(self, devtype, circuit):
        self.devtype = devtype
        self.circuit = circuit
        self.alias = ''
        self.calls = []

    def full(self):
        return {'dev': self.devtype, 'circuit': self.circuit}

    async def set(self, **kw):
        self.calls.append(kw)

    def check_new_data(self):
        self.calls.append('check_new_data')


@pytest.fixture
async def ws():
    Devices[DO]['1_01'] = FakeDevice(DO, '1_01')
    Devices[DI]['1_01'] = FakeDevice(DI, '1_01')
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([(r"/ws", WsHandler)]))
    server.add_sockets([sock])
    client = await tornado.websocket.websocket_connect(f"ws://127.0.0.1:{port}/ws")
    yield client
    client.close()
    server.stop()


async def send(client, message):
    await client.write_message(json.dumps(message))
    # a message is processed before the next one, 'full' marks the end
    await client.write_message(json.dumps({'cmd': 'full', 'dev': 'do', 'circuit': '1_01'}))
    await asyncio.wait_for(client.read_message(), 1)


@pytest.mark.parametrize('message, expected', [
    ({'value': 1}, {'value': 1}),
    ({'value': '0'}, {'value': '0'}),
    ({'value': {'value': 1, 'timeout': 5}}, {'value': 1, 'timeout': 5}),
    ({'value': 1, 'timeout': '2'}, {'value': 1, 'timeout': '2'}),
    ({'pwm_duty': 50}, {'pwm_duty': 50}),
])
async def test_set(ws, message, expected):
    await send(ws, {'cmd': 'set', 'dev': 'do', 'circuit': '1_01', **message})
    assert Devices[DO]['1_01'].calls == [expected]


async def test_value_is_not_the_first_param(ws):
    # the value of a DI does not set the debounce, it is rejected by the schema
    await send(ws, {'cmd': 'set', 'dev': 'di', 'circuit': '1_01', 'value': 5})
    await send(ws, {'cmd': 'set', 'dev': 'di', 'circuit': '1_01', 'debounce': 5})
    assert Devices[DI]['1_01'].calls == [{'debounce': 5}]


@pytest.mark.parametrize('message', [
    {'cmd': 'set', 'dev': 'do', 'circuit': '1_01', 'bogus': 1},
    {'cmd': 'set', 'dev': 'do', 'circuit': '1_01', 'value': [1]},
    {'cmd': 'check_new_data', 'dev': 'do', 'circuit': '1_01'},
    {'cmd': 'set_alias', 'dev': 'do', 'circuit': '1_01', 'value': 'x'},
    {'cmd': '__class__', 'dev': 'do', 'circuit': '1_01'},
])
async def test_rejected(ws, message):
    await send(ws, message)
    assert Devices[DO]['1_01'].calls == []


async def test_full(ws):
    await ws.write_message(json.dumps({'cmd': 'full', 'dev': 'di', 'circuit': '1_01'}))
    assert json.loads(await asyncio.wait_for(ws.read_message(), 1)) == {'dev': 'di', 'circuit': '1_01'}
