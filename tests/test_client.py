import pytest

from evok.devices import devents

from evok.modbus.cache import ENoCacheRegister
from evok.modbus.client import FLOAT32_BE, FLOAT32_LE, Proxy, to_registers

import conftest

BLOCKS = [
    {'start_reg': 0, 'count': 2, 'frequency': 1},
    {'start_reg': 0, 'count': 2, 'frequency': 1, 'type': 'input'},
]


def make_client(holding=None, inputs=None):
    return conftest.make_client(BLOCKS, holding, inputs)


async def test_read_u16():
    client = make_client(holding={1: 0xffff}, inputs={1: 7})
    await client.cache.do_scan(initial=True)
    assert client.read_u16(1) == 0xffff
    assert client.read_u16(1, is_input=True) == 7


async def test_read_u16_errors():
    client = make_client()
    with pytest.raises(ENoCacheRegister):
        client.read_u16(0)
    await client.cache.do_scan(initial=True)
    with pytest.raises(ValueError):
        client.read_u16(5)


async def test_read_float32():
    lo, hi = to_registers(FLOAT32_LE, 1.5)
    assert (lo, hi) == (0x0000, 0x3fc0)                # low word first
    client = make_client(holding={0: lo, 1: hi}, inputs={0: hi, 1: lo})
    await client.cache.do_scan(initial=True)
    assert client.read_float32(0) == 1.5
    assert client.read_float32(0, is_input=True) != 1.5


async def test_read_float32_word_order():
    client = make_client(holding=dict(enumerate(to_registers(FLOAT32_BE, -2.25))))
    await client.cache.do_scan(initial=True)
    assert client.read_float32(0, word_order="big") == -2.25
    assert client.read_float32(0, word_order="little") != -2.25
    with pytest.raises(ValueError):
        client.read_float32(0, word_order="middle")


async def test_read_float32_past_block_end():
    client = make_client()
    await client.cache.do_scan(initial=True)
    with pytest.raises(ENoCacheRegister):
        client.read_float32(1)


async def test_read_u32():
    client = make_client(holding={0: 0x5678, 1: 0x1234}, inputs={0: 0xffff, 1: 0xffff})
    await client.cache.do_scan(initial=True)
    assert client.read_u32(0) == 0x12345678
    assert client.read_u32(0, word_order="big") == 0x56781234
    assert client.read_u32(0, is_input=True) == 0xffffffff
    with pytest.raises(ValueError):
        client.read_u32(0, word_order="middle")
    with pytest.raises(ENoCacheRegister):
        client.read_u32(1)


async def test_read_i32():
    client = make_client(holding={0: 0xfffe, 1: 0xffff}, inputs={0: 0x5678, 1: 0x1234})
    await client.cache.do_scan(initial=True)
    assert client.read_i32(0) == -2
    assert client.read_i32(0, word_order="big") == -65537      # 0xfffffffe vs 0xfffeffff
    assert client.read_i32(0, is_input=True) == 0x12345678
    with pytest.raises(ValueError):
        client.read_i32(0, word_order="middle")
    with pytest.raises(ENoCacheRegister):
        client.read_i32(1)


class FailingDevice:
    devtype, circuit = 'ai', 'x'

    def __init__(self):
        self.fail = True

    async def check_new_data(self):
        if self.fail:
            raise ValueError('broken')
        return False


async def test_failing_device_is_logged_once(caplog):
    client = make_client()
    device = FailingDevice()
    client.eventable_devices.append(device)

    def errors():
        return [r for r in caplog.records if r.levelname == 'ERROR']

    for _ in range(3):
        assert await client.do_scan()
    assert len(errors()) == 1
    device.fail = False
    await client.do_scan()
    assert 'checks new data again' in caplog.text
    device.fail = True
    await client.do_scan()
    assert len(errors()) == 2                               # logged again after it worked


class CountingDevice:
    def __init__(self, circuit):
        self.circuit = circuit
        self.calls = 0

    def full(self):
        self.calls += 1
        return {'dev': 'di', 'circuit': self.circuit}


def test_proxy_full_is_called_by_all_receivers():
    devices = [CountingDevice('1_02'), CountingDevice('1_01')]
    proxy = Proxy(devices)
    states = [{'dev': 'di', 'circuit': '1_02'}, {'dev': 'di', 'circuit': '1_01'}]   # in the order of the scan
    assert proxy.full() == states
    assert proxy.full() == states
    assert [d.calls for d in devices] == [1, 1]            # the states are made once


async def test_do_scan_sends_proxy_of_changed_devices(monkeypatch):
    client = make_client()
    device = CountingDevice('1_01')

    async def check_new_data():
        return True
    device.check_new_data = check_new_data
    client.eventable_devices.append(device)
    events = []
    monkeypatch.setattr(devents, 'status', events.append)
    assert await client.do_scan()
    assert [event.full() for event in events] == [[{'dev': 'di', 'circuit': '1_01'}]]
