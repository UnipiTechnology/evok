from pathlib import Path

import pytest
import yaml

from tmodbus.exceptions import ModbusConnectionError

from evok.devices import Devices
from evok.modbus.cache import ModbusCacheMap

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


class FakeArm:
    """ What the devices see as `arm`: a register cache and a client for writes """

    def __init__(self, cache, client):
        self.cache = cache
        self.client = client
        self.mb_client = client     # IOParser takes the client from here
        self.eventable_devices = []

    async def scan(self, initial=False):
        """ One scan cycle: refresh the cache, then let devices pick up new data """
        assert await self.cache.do_scan(initial=initial)
        return [d for d in self.eventable_devices if await d.check_new_data()]


def make_arm(blocks, holding=None, inputs=None):
    mb = FakeModbus(holding, inputs)
    return FakeArm(ModbusCacheMap(blocks, mb), mb)


@pytest.fixture
def l0306():
    with open(FIXTURES / 'L0306.yaml') as f:
        return yaml.safe_load(f)


@pytest.fixture(autouse=True)
def clean_devices():
    """ Devices is a global registry, keep tests independent """
    for devdict in Devices.values():
        devdict.clear()
    yield
    for devdict in Devices.values():
        devdict.clear()
