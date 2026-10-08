import asyncio
import logging
from types import SimpleNamespace

import pytest
from tmodbus.exceptions import CRCError, IllegalDataAddressError, RequestRetryFailedError

from evok.modbus.cache import ModbusCacheMap, RegisterGroup, ENoCacheRegister, EUnknownRegister
from evok.modbus.scanner import ModbusScanner

from conftest import FakeModbus

BLOCKS = [
    {'start_reg': 0, 'count': 2, 'frequency': 1},
    {'start_reg': 10, 'count': 4, 'frequency': 3},
    {'start_reg': 100, 'count': 2, 'frequency': 1, 'type': 'input'},
]


def test_group_membership():
    g = RegisterGroup(address=10, count=4)
    assert g.is_member(10) and g.is_member(13)
    assert not g.is_member(9) and not g.is_member(14)
    assert g.is_member(12, count=2)
    assert not g.is_member(12, count=3)


def test_group_update_with_offset_is_clipped():
    g = RegisterGroup(address=10, count=4)
    g.update([1, 2, 3], address=12)
    assert g.values == [None, None, 1, 2]
    g.update([7], address=9)            # below the group: ignored
    assert g.values == [None, None, 1, 2]
    g.update([7, 8], address=9)         # starting below the group, was ignored
    assert g.values == [8, None, 1, 2]


def test_group_frequency_divider():
    g = RegisterGroup(address=0, count=1, f_divider=3)
    scanned = []
    for _ in range(7):
        scanned.append(g.f_counter == 0)
        g.tick_counter()
    assert scanned == [True, False, False, True, False, False, True]


async def test_get_register_before_scan_raises():
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    with pytest.raises(ENoCacheRegister):
        cache.get_register(0, 1)


async def test_get_unknown_register_raises():
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    await cache.do_scan(initial=True)
    with pytest.raises(EUnknownRegister, match='holding registers 5..5 are not'):
        cache.get_register(5, 1)
    with pytest.raises(EUnknownRegister, match='input registers 0..0 are not'):
        cache.get_register(0, 1, is_input=True)


def test_unknown_register_is_not_client_error():
    """ A ValueError was reported by the API as a bad request, it is an error of the hardware definition """
    assert not issubclass(EUnknownRegister, ValueError)


async def test_initial_scan_reads_all_groups():
    mb = FakeModbus(holding={0: 1, 1: 2, 10: 3, 13: 4}, inputs={100: 5, 101: 6})
    cache = ModbusCacheMap(BLOCKS, mb)
    assert await cache.do_scan(initial=True)
    assert cache.get_register(0, 2) == [1, 2]
    assert cache.get_register(10, 4) == [3, 0, 0, 4]
    assert cache.get_register(100, 2, is_input=True) == [5, 6]
    assert cache.last_comm_time > 0


async def test_read_past_group_end_raises():
    """ The value was reported as not read yet, it was null forever """
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    await cache.do_scan(initial=True)
    with pytest.raises(EUnknownRegister, match='registers 1..2 are not in one'):
        cache.get_register(1, 2)


async def test_read_over_two_adjacent_groups_raises():
    cache = ModbusCacheMap([{'start_reg': 0, 'count': 2, 'frequency': 1},
                            {'start_reg': 2, 'count': 2, 'frequency': 1}], FakeModbus())
    await cache.do_scan(initial=True)
    with pytest.raises(EUnknownRegister):
        cache.get_register(1, 2)


async def test_no_cached_value_names_the_register():
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    with pytest.raises(ENoCacheRegister, match='register 12$'):
        cache.get_register(12, 1)                           # the address, not the offset 2 in the group
    cache.groups[1].values[0] = 0                           # the register 10 of the group is read
    with pytest.raises(ENoCacheRegister, match='register 11$'):
        cache.get_register(10, 2)                           # the second register is not read


async def test_slow_group_is_scanned_by_divider():
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)
    await cache.do_scan(initial=True)
    mb.holding.update({0: 1, 10: 1})
    seen = []
    for _ in range(3):
        await cache.do_scan()
        seen.append((cache.get_register(0, 1)[0], cache.get_register(10, 1)[0]))
    # fast group follows immediately, slow one every 3rd scan
    assert seen == [(1, 0), (1, 0), (1, 1)]


async def test_failed_scan_keeps_phase_of_slow_groups():
    """ The groups read before an error were ticked, the other ones not, their phases drifted apart """
    blocks = [{'start_reg': 0, 'count': 1, 'frequency': 2}, {'start_reg': 10, 'count': 1, 'frequency': 2}]
    mb = FakeModbus()
    cache = ModbusCacheMap(blocks, mb)
    read = mb.read_holding_registers
    reads = []

    async def flaky(address, **kwargs):
        reads.append(address)
        if address == 10 and len(reads) == 2:
            raise RequestRetryFailedError('no response')
        return await read(address, **kwargs)
    mb.read_holding_registers = flaky
    assert not await cache.do_scan(initial=True)            # the second group fails
    for _ in range(4):
        assert await cache.do_scan()
    # the failed scan is repeated, then both groups are read together every other scan
    assert reads == [0, 10, 0, 10, 0, 10]


async def test_scan_connection_error_returns_false():
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)
    mb.connected = False
    assert not await cache.do_scan(initial=True)
    assert cache.last_comm_time is None


async def test_scan_without_read_is_not_communication():
    """ A unit without register blocks reported a communication on every scan """
    cache = ModbusCacheMap([], FakeModbus())
    assert await cache.do_scan(initial=True)
    assert cache.last_comm_time is None

    # the scans between the reads of a slow group
    cache = ModbusCacheMap([{'start_reg': 0, 'count': 1, 'frequency': 3}], FakeModbus())
    assert await cache.do_scan(initial=True)
    last_comm_time = cache.last_comm_time
    assert await cache.do_scan()
    assert cache.last_comm_time == last_comm_time


async def test_set_register_and_get_register_async():
    mb = FakeModbus(holding={11: 42})
    cache = ModbusCacheMap(BLOCKS, mb)
    await cache.do_scan(initial=True)
    cache.set_register(12, [7])
    assert cache.get_register(12, 1) == [7]
    mb.holding[11] = 43
    assert await cache.get_register_async(11, 1) == [43]
    assert cache.get_register(11, 1) == [43]


async def test_set_register_skips_registers_out_of_blocks():
    """ A successful write out of the blocks raised an error """
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    await cache.do_scan(initial=True)
    cache.set_register(1000, [1])
    cache.set_register(9, [1, 2])                           # the register 9 is before the group 10..13
    cache.set_register(13, [3, 4])                          # the register 14 is past it
    assert cache.get_register(10, 4) == [2, 0, 0, 3]


async def test_get_register_async_out_of_blocks():
    """ The read-modify-write of a bit out of the blocks failed before the read """
    cache = ModbusCacheMap(BLOCKS, FakeModbus(holding={1000: 5}))
    assert await cache.get_register_async(1000) == [5]


@pytest.mark.parametrize('error', [
    RequestRetryFailedError('retries exhausted'),           # the transport retries a lost connection
    CRCError('noise', response_bytes=b'\x01'),
    IllegalDataAddressError(0x03),
    TimeoutError('no response'),
])
async def test_scan_error_returns_false(error):
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)

    async def fail(*args, **kwargs):
        raise error
    read = mb.read_holding_registers
    mb.read_holding_registers = fail
    assert not await cache.do_scan(initial=True)
    assert cache.scan_error is error
    mb.read_holding_registers = read
    assert await cache.do_scan(initial=True)
    assert cache.scan_error is None


def test_overlapping_blocks_are_rejected():
    blocks = [{'start_reg': 0, 'count': 4, 'frequency': 1}, {'start_reg': 3, 'count': 2, 'frequency': 5}]
    with pytest.raises(ValueError, match='overlaps the block of registers 0..3'):
        ModbusCacheMap(blocks, FakeModbus())
    # the holding and input registers are separate, adjacent blocks do not overlap
    ModbusCacheMap([blocks[0], {**blocks[1], 'type': 'input'}, {'start_reg': 4, 'count': 1, 'frequency': 1}],
                   FakeModbus())


@pytest.mark.parametrize('block', [
    {'start_reg': 0, 'count': 2, 'frequency': 0},           # never scanned again
    {'start_reg': 0, 'count': 2},
    {'start_reg': 0, 'count': 0, 'frequency': 1},
    {'start_reg': -1, 'count': 2, 'frequency': 1},
    {'start_reg': '0', 'count': 2, 'frequency': 1},
    {'start_reg': 0, 'count': 2, 'frequency': 1, 'type': 'inputs'},
])
def test_invalid_block_is_rejected(block):
    with pytest.raises(ValueError, match='Register block'):
        ModbusCacheMap([block], FakeModbus())


async def test_initial_scan_is_retried_after_an_error(caplog):
    """ An error of the first scan stopped the scan task, the unit was never created """
    caplog.set_level(logging.INFO, logger='evok')               # "is connected" is logged as info
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)
    populated = asyncio.Event()
    failures = [RequestRetryFailedError('retries exhausted')] * 2
    read = mb.read_holding_registers

    async def flaky(*args, **kwargs):
        if failures:
            raise failures.pop()
        return await read(*args, **kwargs)
    mb.read_holding_registers = flaky
    slave = SimpleNamespace(cache=cache, circuit='1', populated=False, INITIAL_SCAN_INTERVAL=0, scan_interval=10,
                            parser=SimpleNamespace(populate=populated.set))
    task = asyncio.create_task(ModbusScanner._scan_loop(slave))
    await asyncio.wait_for(populated.wait(), 1)
    task.cancel()
    assert caplog.text.count("Waiting for device '1'") == 1     # the same error is logged once
    assert "Device '1' is connected" in caplog.text
