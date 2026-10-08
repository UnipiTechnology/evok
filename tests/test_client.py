import pytest

from evok.devices import devents

from evok.modbus.cache import ENoCacheRegister, EUnknownRegister
from evok.modbus.client import Proxy

import conftest

BLOCKS = [
    {'start_reg': 0, 'count': 2, 'frequency': 1},
    {'start_reg': 0, 'count': 2, 'frequency': 1, 'type': 'input'},
]


def make_client(holding=None, inputs=None):
    return conftest.make_client(BLOCKS, holding, inputs)


async def test_read_registers():
    client = make_client(holding={0: 1, 1: 0xffff}, inputs={1: 7})
    with pytest.raises(ENoCacheRegister):                   # before the first scan
        client.read_registers(0)
    await client.cache.do_scan(initial=True)
    assert client.read_registers(0, 2) == [1, 0xffff]
    assert client.read_registers(1, is_input=True) == [7]
    with pytest.raises(EUnknownRegister):                   # outside of register blocks
        client.read_registers(5)
    with pytest.raises(EUnknownRegister):                   # past the end of the block, never cached
        client.read_registers(1, 2)


async def test_write_registers_updates_cache():
    client = make_client()
    await client.cache.do_scan(initial=True)
    await client.write_registers(0, [5])
    await client.write_registers(0, [6, 7])
    assert client.mb_client.writes == [('reg', 0, 5), ('regs', 0, [6, 7])]
    assert client.read_registers(0, 2) == [6, 7]


async def test_write_registers_out_of_blocks():
    """ The write succeeded, the update of the cache raised an error reported by the API """
    client = make_client()
    await client.cache.do_scan(initial=True)
    await client.write_registers(1, [8, 9])                 # the register 2 is not in a block
    assert client.mb_client.writes == [('regs', 1, [8, 9])]
    assert client.read_registers(1) == [8]
    await client.write_registers(1000, [1])
    assert client.mb_client.writes[-1] == ('reg', 1000, 1)


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
