from pathlib import Path

import pytest
import yaml

from tmodbus.exceptions import ModbusConnectionError

from evok.devices import Devices
from evok.modbus.cache import ModbusCacheMap
from evok.modbus.client import Client

FIXTURES = Path(__file__).parent / 'fixtures'


class FakeModbus:
    """ In-memory Modbus unit with the subset of the AsyncModbusClient API used by evok """

    def __init__(self, holding=None, inputs=None):
        self.holding: dict[int, int] = dict(holding or {})
        self.inputs: dict[int, int] = dict(inputs or {})
        self.coils: dict[int, int] = {}
        self.writes: list[tuple] = []
        self.connected = True

    def _read(self, regs, address, quantity):
        if not self.connected:
            raise ModbusConnectionError("fake unit disconnected")
        return [regs.get(address + i, 0) for i in range(quantity)]

    async def read_holding_registers(self, address, quantity=1):
        return self._read(self.holding, address, quantity)

    async def read_input_registers(self, address, quantity=1):
        return self._read(self.inputs, address, quantity)

    async def write_single_coil(self, address, value):
        self.writes.append(('coil', address, value))
        self.coils[address] = value

    async def write_single_register(self, address, value):
        self.writes.append(('reg', address, value))
        self.holding[address] = value

    async def write_multiple_registers(self, address, values):
        self.writes.append(('regs', address, list(values)))
        for i, v in enumerate(values):
            self.holding[address + i] = v

    async def write_uint32(self, address, value):
        self.writes.append(('uint32', address, value))
        # word_order="little": low word first
        self.holding[address] = value & 0xffff
        self.holding[address + 1] = value >> 16


def make_client(blocks, holding=None, inputs=None):
    mb = FakeModbus(holding, inputs)
    return Client('test', mb, ModbusCacheMap(blocks, mb))


async def scan(client, initial=False):
    """ One scan cycle: refresh the cache, then let devices pick up new data """
    assert await client.cache.do_scan(initial=initial)
    return [d for d in client.eventable_devices if await d.check_new_data()]


@pytest.fixture
def l0306():
    with open(FIXTURES / 'L0306.yaml') as f:
        return yaml.safe_load(f)


@pytest.fixture(autouse=True)
def clean_devices():
    """ Devices is a global registry, keep tests independent """
    def clear():
        for devdict in Devices.values():
            devdict.clear()
        Devices.aliases.alias_dict.clear()
        Devices.aliases.initial_dict.clear()
    clear()
    yield
    clear()
