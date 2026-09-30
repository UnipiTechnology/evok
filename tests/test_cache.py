import pytest

from evok.modbus.cache import ModbusCacheMap, RegisterGroup, ENoCacheRegister

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
        cache.get_register(1, 0)


async def test_get_unknown_register_raises():
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    await cache.do_scan(initial=True)
    with pytest.raises(ValueError):
        cache.get_register(1, 5)
    with pytest.raises(ValueError):
        cache.get_register(1, 0, is_input=True)


async def test_initial_scan_reads_all_groups():
    mb = FakeModbus(holding={0: 1, 1: 2, 10: 3, 13: 4}, inputs={100: 5, 101: 6})
    cache = ModbusCacheMap(BLOCKS, mb)
    assert await cache.do_scan(initial=True)
    assert cache.get_register(2, 0) == [1, 2]
    assert cache.get_register(4, 10) == [3, 0, 0, 4]
    assert cache.get_register(2, 100, is_input=True) == [5, 6]
    assert cache.last_comm_time > 0


async def test_read_past_group_end_raises():
    cache = ModbusCacheMap(BLOCKS, FakeModbus())
    await cache.do_scan(initial=True)
    with pytest.raises(ENoCacheRegister):
        cache.get_register(2, 1)


async def test_slow_group_is_scanned_by_divider():
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)
    await cache.do_scan(initial=True)
    mb.holding.update({0: 1, 10: 1})
    seen = []
    for _ in range(3):
        await cache.do_scan()
        seen.append((cache.get_register(1, 0)[0], cache.get_register(1, 10)[0]))
    # fast group follows immediately, slow one every 3rd scan
    assert seen == [(1, 0), (1, 0), (1, 1)]


async def test_scan_connection_error_returns_false():
    mb = FakeModbus()
    cache = ModbusCacheMap(BLOCKS, mb)
    mb.connected = False
    assert not await cache.do_scan(initial=True)
    assert cache.last_comm_time == 0


async def test_set_register_and_get_register_async():
    mb = FakeModbus(holding={11: 42})
    cache = ModbusCacheMap(BLOCKS, mb)
    await cache.do_scan(initial=True)
    cache.set_register(12, [7])
    assert cache.get_register(1, 12) == [7]
    mb.holding[11] = 43
    assert await cache.get_register_async(1, 11) == [43]
    assert cache.get_register(1, 11) == [43]
