from types import SimpleNamespace

import pytest
from tornado_jsonrpc2.exceptions import InvalidParams, MethodNotFound

from evok.devices import Devices, DO, RO, to_float
from evok.rpc_handler import Handler, create_response


class FakeOutput:
    def __init__(self, devtype):
        self.devtype = devtype
        self.circuit = '1_01'
        self.alias = ''
        self.values = []

    def full(self):
        return {'dev': self.devtype, 'circuit': self.circuit}

    async def set(self, value=None, pulse_duration=None):
        if value is not None and int(value) > 1:
            raise ValueError('Value out of range')
        if pulse_duration is not None:
            # as WithPulse._check_pulse() of an output, RPC passes pulse_duration to it
            pulse_duration = to_float(pulse_duration)
            if pulse_duration <= 0:
                raise ValueError('pulse_duration must be positive')
        self.values.append((value, pulse_duration))


@pytest.fixture
def outputs():
    Devices[DO]['1_01'] = FakeOutput(DO)
    Devices[RO]['1_01'] = FakeOutput(RO)
    return Devices[DO]['1_01'], Devices[RO]['1_01']


def call(method, params=None):
    request = SimpleNamespace(method=method)
    if params is not None:
        request.params = params
    return create_response(request, Handler.__new__(Handler))


@pytest.mark.parametrize('method', ['output_set', 'relay_set'])
@pytest.mark.parametrize('value, expected', [('0', 0), ('1', 1), (0, 0), (1, 1), (True, 1), (False, 0),
                                             ('true', 1), ('off', 0)])
async def test_set_value(outputs, method, value, expected):
    assert await call(method, ['1_01', value]) == expected
    device = outputs[0] if method == 'output_set' else outputs[1]
    assert device.values == [(expected, None)]


async def test_set_by_name(outputs):
    assert await call('output_set', {'circuit': '1_01', 'value': '1'}) == 1


async def test_output_set_for_time_string_pulse_duration(outputs):
    await call('output_set_for_time', ['1_01', 1, '5'])
    assert outputs[0].values == [(1, 5.0)]


async def test_relay_set_for_time(outputs):
    assert await call('relay_set_for_time', ['1_01', '1', '5']) == {'dev': 'ro', 'circuit': '1_01'}
    assert await call('relay_set_for_time', {'circuit': '1_01', 'value': 0, 'pulse_duration': 0.5})
    assert outputs[1].values == [('1', 5.0), (0, 0.5)]


@pytest.mark.parametrize('name', ['pulse_duration', 'timeout'])
async def test_output_set_for_time_by_name(outputs, name):
    # timeout is a deprecated alias of pulse_duration
    await call('output_set_for_time', {'circuit': '1_01', 'value': 1, name: 5})
    assert outputs[0].values == [(1, 5.0)]


@pytest.mark.parametrize('method, params', [
    ('output_set', ['1_01']),                          # missing param
    ('output_set', {'circuit': '1_01', 'val': 1}),     # unknown param
    ('output_set', ['1_01', 1, 2]),                    # too many params
    ('output_set', '1_01'),                            # params are neither an array nor an object
    ('output_set', ['1_01', 'x']),                     # invalid value
    ('output_set', ['1_01', '2']),
    ('output_set', ['9_99', 1]),                       # unknown circuit
    ('output_set_for_time', ['1_01', 1, 0]),           # invalid pulse_duration
    ('output_set_for_time', ['1_01', 1, 'x']),
    ('output_set_for_time', ['1_01', 1]),              # missing pulse_duration
    ('output_set_for_time', {'circuit': '1_01', 'value': 1, 'pulse_duration': 5, 'timeout': 5}),  # both
    ('relay_set_for_time', ['1_01', 1, 0]),            # invalid pulse_duration
    ('relay_set_for_time', ['1_01', 1, 'x']),
    ('relay_set_for_time', ['1_01', 1]),               # missing pulse_duration
    ('relay_set_for_time', {'circuit': '1_01', 'value': 1, 'timeout': 5}),  # no deprecated alias
])
async def test_invalid_params(outputs, method, params):
    with pytest.raises(InvalidParams):
        await call(method, params)
    assert outputs[0].values == [] and outputs[1].values == []


async def test_unknown_method():
    with pytest.raises(MethodNotFound):
        await call('di_get', ['1_01'])


@pytest.fixture
async def rpc():
    """ JSON-RPC over HTTP, the errors are converted also by tornado_jsonrpc2 """
    import json
    import tornado.httpclient
    import tornado.httpserver
    import tornado.testing
    import tornado.web
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([(r"/rpc", Handler)]))
    server.add_sockets([sock])

    async def request(method, params):
        body = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1})
        response = await tornado.httpclient.AsyncHTTPClient().fetch(
            f"http://127.0.0.1:{port}/rpc", method='POST', body=body)
        return json.loads(response.body)
    yield request
    server.stop()


class FailingOutput(FakeOutput):
    def __init__(self, error):
        super().__init__(DO)
        self.error = error

    async def set(self, **kw):
        raise self.error


async def test_unavailable_unit_over_http(rpc):
    """ tornado_jsonrpc2 returned it as -32603 Internal error """
    from evok.errors import UnitCommunicationError
    Devices[DO]['1_01'] = FailingOutput(UnitCommunicationError("Unit '1': TimeoutError: no response"))
    reply = await rpc('output_set', ['1_01', 1])
    assert reply['error'] == {'code': -32000, 'message': "Unit unavailable: Unit '1': TimeoutError: no response"}


async def test_internal_error_over_http_is_logged_not_sent(rpc, caplog):
    """ The message of the error was sent to the client, it was not logged """
    Devices[DO]['1_01'] = FailingOutput(KeyError('internal detail'))
    reply = await rpc('output_set', ['1_01', 1])
    assert reply['error'] == {'code': -32603, 'message': 'Internal error: internal'}
    assert "RPC output_set: 'internal detail'" in caplog.text and 'Traceback' in caplog.text


async def test_invalid_params_over_http(rpc, outputs):
    reply = await rpc('output_set_for_time', ['1_01', 1, 0])
    assert reply['error']['code'] == -32602
