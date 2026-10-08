import asyncio
import json

import pytest
import tornado.httpserver
import tornado.testing
import tornado.web
import tornado.websocket

from evok.devices import Devices, DI, DO, SENSOR, WATCHDOG
from evok.ws_handler import WsHandler, registered_ws


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
async def ws(handlers):
    yield handlers[0]


@pytest.fixture
async def handlers():
    """ A client and the server side handler of the connection """
    Devices[DO]['1_01'] = FakeDevice(DO, '1_01')
    Devices[DI]['1_01'] = FakeDevice(DI, '1_01')
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([(r"/ws", WsHandler)]))
    server.add_sockets([sock])
    client = await tornado.websocket.websocket_connect(f"ws://127.0.0.1:{port}/ws")
    await send(client, {'cmd': 'filter', 'devices': ['default']})
    yield client, next(iter(registered_ws['all']))
    client.close()
    server.stop()
    registered_ws.clear()


MARK = {'cmd': 'full', 'dev': 'do', 'circuit': '1_01'}


async def send(client, message):
    """ Send a message, return the replies to it """
    await client.write_message(json.dumps(message))
    # messages are processed in order, the reply to 'full' marks the end
    await client.write_message(json.dumps(MARK))
    replies = []
    while (reply := json.loads(await asyncio.wait_for(client.read_message(), 1))) != Devices[DO]['1_01'].full():
        replies.append(reply)
    return replies




@pytest.mark.parametrize('message, expected', [
    ({'value': 1}, {'value': 1}),
    ({'value': '0'}, {'value': '0'}),
    ({'value': {'value': 1, 'timeout': 5}}, {'value': 1, 'timeout': 5}),
    ({'value': 1, 'timeout': '2'}, {'value': 1, 'timeout': '2'}),
    ({'value': {'value': 1, 'pulse_duration': 5}}, {'value': 1, 'pulse_duration': 5}),
    ({'value': 1, 'pulse_duration': '2'}, {'value': 1, 'pulse_duration': '2'}),
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
    replies = await send(ws, message)
    assert Devices[DO]['1_01'].calls == []
    assert [reply['success'] for reply in replies] == [False]


async def test_full(ws):
    await ws.write_message(json.dumps({'cmd': 'full', 'dev': 'di', 'circuit': '1_01'}))
    assert json.loads(await asyncio.wait_for(ws.read_message(), 1)) == {'dev': 'di', 'circuit': '1_01'}


@pytest.mark.parametrize('message, error', [
    ('not json', 'JSONDecodeError'),
    ([1], 'ValueError'),
    ({}, 'ValueError'),                                              # no command
    ({'cmd': 'set', 'dev': 'do'}, 'ValueError'),                     # no circuit
    ({'cmd': 'set', 'dev': 'do', 'circuit': '9_99'}, 'DeviceNotFound'),
    ({'cmd': 'set', 'dev': 'do', 'circuit': '1_01', 'bogus': 1}, 'ValidationError'),
    ({'cmd': 'filter', 'devices': 'di'}, 'ValueError'),
    ({'cmd': 'filter', 'devices': ['foo']}, 'ValueError'),
])
async def test_error_reply(ws, message, error):
    await ws.write_message(message if isinstance(message, str) else json.dumps(message))
    reply = json.loads(await asyncio.wait_for(ws.read_message(), 1))
    assert reply['success'] is False
    assert list(reply['errors']) == [error]


@pytest.mark.parametrize('devices, expected', [
    (['input'], ['di']),                     # altnames are converted
    (['di', 'foo'], ['di']),                 # unknown types are skipped
    ([], []),
    (['default'], ['default']),
])
async def test_filter(handlers, devices, expected):
    client, handler = handlers
    await send(client, {'cmd': 'filter', 'devices': ['do']})
    assert await send(client, {'cmd': 'filter', 'devices': devices}) == []
    assert handler.filter == expected


async def test_event_with_altname_filter(handlers):
    client, handler = handlers
    await send(client, {'cmd': 'filter', 'devices': ['input']})
    handler.on_event(Devices[DI]['1_01'])
    assert await send(client, {'cmd': 'filter', 'devices': ['input']}) == [[{'dev': 'di', 'circuit': '1_01'}]]


@pytest.mark.parametrize('all_filtered, devices, expected', [
    (True, ['di'], [{'dev': 'di', 'circuit': '1_01'}]),
    (True, ['default'], [{'dev': 'di', 'circuit': '1_01'}]),        # DO is not in the default 'all'
    (False, ['di'], [{'dev': 'do', 'circuit': '1_01'}, {'dev': 'di', 'circuit': '1_01'}]),
])
async def test_all(handlers, all_filtered, devices, expected):
    client, handler = handlers
    handler.all_filtered = all_filtered
    await send(client, {'cmd': 'filter', 'devices': devices})
    assert await send(client, {'cmd': 'all'}) == [expected]


class FakeProxy:
    """ A change of Modbus devices, full() returns a list """
    def __init__(self, *devices):
        self.devices = devices

    def full(self):
        return [device.full() for device in self.devices]


@pytest.mark.parametrize('devices, event, expected', [
    (['default'], lambda: Devices[DI]['1_01'], [{'dev': 'di', 'circuit': '1_01'}]),
    (['default'], lambda: FakeProxy(Devices[DI]['1_01'], Devices[DO]['1_01']),
     [{'dev': 'di', 'circuit': '1_01'}, {'dev': 'do', 'circuit': '1_01'}]),
    (['do'], lambda: Devices[DI]['1_01'], None),
    (['do'], lambda: FakeProxy(Devices[DI]['1_01'], Devices[DO]['1_01']), [{'dev': 'do', 'circuit': '1_01'}]),
])
async def test_event_is_a_list(handlers, devices, event, expected):
    client, handler = handlers
    await send(client, {'cmd': 'filter', 'devices': devices})
    handler.on_event(event())
    replies = await send(client, {'cmd': 'filter', 'devices': devices})
    assert replies == ([expected] if expected else [])


class FakeState:
    """ A device whose 'dev' in full() is not its device type """
    def __init__(self, dev):
        self.dev = dev

    def full(self):
        return {'dev': self.dev, 'circuit': '1'}


@pytest.mark.parametrize('devices, dev', [
    (['wd'], 'wd'), (['watchdog'], 'wd'),
    (['temp'], 'temp'), (['sensor'], 'temp'), (['sensor'], '1wdevice'),
])
async def test_event_filter_by_device_type(handlers, devices, dev):
    client, handler = handlers
    await send(client, {'cmd': 'filter', 'devices': devices})
    handler.on_event(FakeState(dev))
    assert await send(client, {'cmd': 'filter', 'devices': devices}) == [[{'dev': dev, 'circuit': '1'}]]
