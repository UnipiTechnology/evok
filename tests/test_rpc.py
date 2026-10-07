from types import SimpleNamespace

import pytest
from tornado_jsonrpc2.exceptions import InvalidParams, MethodNotFound

from evok.devices import Devices, DO, RO
from evok.rpc_handler import Handler, create_response


class FakeOutput:
    def __init__(self, devtype):
        self.devtype = devtype
        self.circuit = '1_01'
        self.alias = ''
        self.values = []

    def full(self):
        return {'dev': self.devtype, 'circuit': self.circuit}

    async def set(self, value=None, timeout=None):
        if value is not None and int(value) > 1:
            raise ValueError('Value out of range')
        self.values.append((value, timeout))


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
@pytest.mark.parametrize('value, expected', [('0', 0), ('1', 1), (0, 0), (1, 1), (True, 1), (False, 0)])
async def test_set_value(outputs, method, value, expected):
    assert await call(method, ['1_01', value]) == expected
    device = outputs[0] if method == 'output_set' else outputs[1]
    assert device.values == [(expected, None)]


async def test_set_by_name(outputs):
    assert await call('output_set', {'circuit': '1_01', 'value': '1'}) == 1


async def test_output_set_for_time_string_timeout(outputs):
    await call('output_set_for_time', ['1_01', 1, '5'])
    assert outputs[0].values == [(1, 5.0)]


@pytest.mark.parametrize('method, params', [
    ('output_set', ['1_01']),                          # missing param
    ('output_set', {'circuit': '1_01', 'val': 1}),     # unknown param
    ('output_set', ['1_01', 1, 2]),                    # too many params
    ('output_set', '1_01'),                            # params are neither an array nor an object
    ('output_set', ['1_01', 'on']),                    # invalid value
    ('output_set', ['9_99', 1]),                       # unknown circuit
    ('output_set_for_time', ['1_01', 1, 0]),           # invalid timeout
    ('output_set_for_time', ['1_01', 1, 'x']),
])
async def test_invalid_params(outputs, method, params):
    with pytest.raises(InvalidParams):
        await call(method, params)
    assert outputs[0].values == []


async def test_unknown_method():
    with pytest.raises(MethodNotFound):
        await call('di_get', ['1_01'])
