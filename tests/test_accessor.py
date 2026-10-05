import math

import pytest

from evok.modbus.cache import ENoCacheRegister
from evok.modbus.client import (
    FLOAT32_BE, FLOAT32_LE, Accessor, AccessorBit, AccessorFactory, AccessorFloat32, AccessorI16,
    AccessorI32, AccessorU16, AccessorU32, to_registers,
)

import conftest

BLOCKS = [
    {'start_reg': 0, 'count': 4, 'frequency': 1},
    {'start_reg': 0, 'count': 4, 'frequency': 1, 'type': 'input'},
]


async def make_client(holding=None, inputs=None):
    client = conftest.make_client(BLOCKS, holding, inputs)
    await client.cache.do_scan(initial=True)
    return client


def regs(values, start=0):
    return {start + i: v for i, v in enumerate(values)}


@pytest.mark.parametrize('datatype, cls', [
    ('uint16', AccessorU16), ('int16', AccessorI16), ('signed16', AccessorI16),
    ('uint32', AccessorU32), ('int32', AccessorI32), ('float32', AccessorFloat32),
])
def test_factory_classes(datatype, cls):
    accessor = AccessorFactory.get(2, datatype, is_input=True)
    assert type(accessor) is cls
    assert (accessor.index, accessor.is_input) == (2, True)


def test_factory_default_is_uint16():
    assert type(AccessorFactory.get(0)) is AccessorU16


async def test_factory_unknown_datatype(caplog):
    accessor = AccessorFactory.get(1, 'bogus')
    assert type(accessor) is Accessor
    assert 'Unknown datatype "bogus"' in caplog.text
    client = await make_client(holding={1: 5})
    assert accessor.read(client) is None


def test_factory_word_order_only_for_32bit():
    assert AccessorFactory.get(0, 'uint32', word_order='big').word_order == 'big'
    assert AccessorFactory.get(0, 'float32').word_order == 'little'
    with pytest.raises(ValueError):
        AccessorFactory.get(0, 'uint16', word_order='big')
    with pytest.raises(ValueError):
        AccessorFactory.get(0, 'int32', word_order='middle')


async def test_read_16bit():
    client = await make_client(holding={0: 0xfffe}, inputs={0: 7})
    assert AccessorFactory.get(0, 'uint16').read(client) == 0xfffe
    assert AccessorFactory.get(0, 'int16').read(client) == -2
    assert AccessorFactory.get(0, 'uint16', is_input=True).read(client) == 7


async def test_read_32bit_word_order():
    # low word first
    client = await make_client(holding={0: 0x5678, 1: 0x1234, 2: 0x1234, 3: 0x5678})
    assert AccessorFactory.get(0, 'uint32').read(client) == 0x12345678
    assert AccessorFactory.get(2, 'uint32', word_order='big').read(client) == 0x12345678
    client = await make_client(holding={0: 0xffff, 1: 0xffff})
    assert AccessorFactory.get(0, 'int32').read(client) == -1


async def test_read_float32():
    client = await make_client(holding=regs(to_registers(FLOAT32_LE, 1.5)),
                               inputs=regs(to_registers(FLOAT32_BE, -2.25)))
    assert AccessorFactory.get(0, 'float32').read(client) == 1.5
    assert AccessorFactory.get(0, 'float32', is_input=True, word_order='big').read(client) == -2.25


async def test_read_float32_nan_passes_through():
    client = await make_client(holding=regs(to_registers(FLOAT32_LE, math.nan)))
    assert math.isnan(AccessorFactory.get(0, 'float32', ratio=2, decimals=1).read(client))


@pytest.mark.parametrize('kwargs, expected', [
    ({}, 1234),
    ({'ratio': 0.1}, pytest.approx(123.4)),
    ({'offset': -34}, 1200),
    ({'ratio': 2, 'offset': 1}, 2469),
    ({'decimals': 0, 'ratio': 0.001}, 1.0),
    ({'decimals': 2, 'ratio': 0.001}, 1.23),
    ({'decimals': 1, 'ratio': 0.01, 'offset': 0.5}, 12.8),
])
async def test_transformation(kwargs, expected):
    client = await make_client(holding={0: 1234})
    assert AccessorFactory.get(0, 'uint16', **kwargs).read(client) == expected


async def test_read_raw_ignores_transformation():
    client = await make_client(holding={0: 10})
    accessor = AccessorFactory.get(0, 'uint16', ratio=3, offset=1)
    assert accessor.read_raw(client) == 10
    assert accessor.read(client) == 31


async def test_read_errors_propagate():
    client = conftest.make_client(BLOCKS)
    with pytest.raises(ENoCacheRegister):  # before the first scan
        AccessorFactory.get(0, 'uint16').read(client)
    await client.cache.do_scan(initial=True)
    with pytest.raises(ValueError):  # outside of register blocks
        AccessorFactory.get(10, 'uint16').read(client)
    with pytest.raises(ENoCacheRegister):  # second word outside of the block
        AccessorFactory.get(3, 'uint32').read(client)


def test_refactor_keeps_only_index_and_is_input():
    accessor = AccessorFactory.get(3, 'int32', is_input=True, ratio=2, offset=1,
                               decimals=1, word_order='big')
    same = accessor.refactor('int32')
    assert type(same) is AccessorI32 and same is not accessor
    assert same.index == 3
    assert same.params() == dict(is_input=True, ratio=1, offset=0, decimals=None, word_order='little')

    changed = accessor.refactor('float32', ratio=5, offset=-1, decimals=2, word_order='big')
    assert type(changed) is AccessorFloat32
    assert changed.params() == dict(is_input=True, ratio=5, offset=-1, decimals=2, word_order='big')


def test_refactor_defaults():
    accessor = AccessorFactory.get(1, 'float32', ratio=2, word_order='big').refactor()
    assert type(accessor) is AccessorU16
    assert (accessor.index, accessor.params()) == (1, dict(is_input=False, ratio=1, offset=0, decimals=None))


def test_refactor_word_order_only_for_32bit():
    accessor = AccessorFactory.get(0, 'uint32', word_order='big')
    assert type(accessor.refactor('uint16')) is AccessorU16
    with pytest.raises(ValueError):
        accessor.refactor('uint16', word_order='big')
    assert type(accessor.refactor('bogus')) is Accessor


async def test_read_bit():
    client = await make_client(holding={0: 0b0101}, inputs={1: 0x8000})
    assert [AccessorBit(0, 1 << i).read(client) for i in range(4)] == [1, 0, 1, 0]
    assert AccessorBit(1, 0x8000, is_input=True).read(client) == 1
    assert AccessorBit(1, 0x8000).read(client) == 0
    assert AccessorBit(0, 0b0101).params()['mask'] == 0b0101
