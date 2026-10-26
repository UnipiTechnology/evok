""" The changes of the devices of a Modbus unit under its lock, Client.change() and set_devices() """
import asyncio
from types import SimpleNamespace

import pytest
from conftest import make_client, scan
from test_bus_priority import SlowBus
from tmodbus import AsyncModbusClient, AsyncSmartTransport, AsyncTcpTransport
from tmodbus.exceptions import CRCError, RequestRetryFailedError

from evok import devents
from evok.blocks import sequencer, start_pulse
from evok.devices import DI, DO, NV_SAVE, WATCHDOG, Devices
from evok.errors import UnitCommunicationError, UnitUnavailable
from evok.handlers_base import client_error
from evok.modbus import set_devices
from evok.modbus.analog import AnalogOutputBrain
from evok.modbus.builder import IOParser
from evok.modbus.cache import ModbusCacheMap
from evok.modbus.client import AccessorBit, AccessorU16, AccessorU32, Client, device_registers
from evok.modbus.scanner import ModbusScanner
from evok.modbus.transport import BusTransport
from evok.rpc_handler import Handler, UnitUnavailableError, create_response


@pytest.fixture
def events(monkeypatch):
    sent = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: sent.append(device))
    return sent


@pytest.fixture
def units(l0306):
    """ Populated L0306 units by their names """
    async def factory(*names):
        clients = []
        for name in names:
            client = make_client(l0306['modbus_register_blocks'])
            IOParser(client, l0306['modbus_features'], name).populate()
            await scan(client, initial=True)
            clients.append(client)
        return clients
    return factory


def coil_drives_register(client, coil, reg, mask):
    """ The firmware sets the bit of the register by the coil, the fake unit does not """
    write = client.mb_client.write_single_coil

    async def write_single_coil(address, value):
        await write(address, value)
        if address == coil:
            holding = client.mb_client.holding
            holding[reg] = holding.get(reg, 0) | mask if value else holding.get(reg, 0) & ~mask
    client.mb_client.write_single_coil = write_single_coil


async def test_state_and_event_follow_the_change(units, events):
    """ full() after a set was the state of the cache before the write, the event came with the next scan """
    client, = await units('1')
    coil_drives_register(client, 0, 1, 0b01)
    do = Devices.by_name(DO, '1_01')
    state, = await set_devices([(do, {'value': 1})])
    assert state['value'] == 1
    assert [device.full() for proxy in events for device in proxy.changeset] == [do.full()]


async def test_change_reads_all_groups_and_keeps_their_phase():
    client = make_client([{'start_reg': 0, 'count': 1, 'scan_divider': 1},
                          {'start_reg': 10, 'count': 1, 'scan_divider': 3}])
    await client.cache.do_scan(initial=True)
    await client.cache.do_scan()
    counters = [group.f_counter for group in client.cache.groups]

    async def firmware():
        client.mb_client.holding[10] = 7                    # a register of the slow group
    await client.change(firmware)
    assert client.read_registers(10) == [7]
    assert [group.f_counter for group in client.cache.groups] == counters


SLOW_BLOCKS = [{'start_reg': 0, 'count': 1, 'scan_divider': 1},
               {'start_reg': 10, 'count': 1, 'scan_divider': 3},
               {'start_reg': 20, 'count': 1, 'scan_divider': 3},
               {'start_reg': 30, 'count': 1, 'scan_divider': 3, 'type': 'input'}]


def recorded_reads(client):
    """ The addresses of the blocks read by the fake unit """
    reads = []
    for name in ('read_holding_registers', 'read_input_registers'):
        read = getattr(client.mb_client, name)

        async def recorded(address, quantity=1, _read=read):
            reads.append(address)
            return await _read(address, quantity)
        setattr(client.mb_client, name, recorded)
    return reads


async def test_change_of_devices_reads_the_fast_and_their_groups():
    """ The blocks of the states of the devices and of the written registers, not the other slow blocks """
    client = make_client(SLOW_BLOCKS)
    await client.cache.do_scan(initial=True)
    await client.cache.do_scan()
    counters = [group.f_counter for group in client.cache.groups + client.cache.igroups]
    reads = recorded_reads(client)
    device = SimpleNamespace(accessor=AccessorU16(30, is_input=True), accessor_setting=AccessorU16(10))

    async def operation():
        await client.write_registers(20, [5])
    await client.change(operation, devices=[device])
    assert reads == [0, 20, 30]
    assert [group.f_counter for group in client.cache.groups + client.cache.igroups] == counters


def delayed_unit(client):
    """ The unit sets a written holding register later, by apply(), e.g. the mode of an AI of xS52 """
    pending = {}
    write = client.mb_client.write_single_register

    async def delayed(address, value):
        client.mb_client.writes.append(('reg', address, value))
        pending[address] = value
    client.mb_client.write_single_register = delayed

    async def apply(accept=True):
        for address, value in pending.items():
            if accept:
                await write(address, value)
        pending.clear()
    return apply


async def test_written_value_is_kept_after_the_read(monkeypatch):
    """ The read after the write returned the old value of a unit setting it with a delay, the state and the event
        showed the old mode, the change seemed to fail
    """
    monkeypatch.setattr('evok.modbus.client.REREAD_DELAY', 0.01)
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    delayed_unit(client)
    reads = recorded_reads(client)
    await client.change(lambda: client.write_registers(20, [2]), devices=[])
    assert reads == [0, 20]                                 # read, the unit returned 1
    assert client.read_registers(20) == [2]


@pytest.mark.parametrize('accept, value', [(True, 2), (False, 1)])
async def test_written_block_is_read_after_the_pin(monkeypatch, accept, value):
    """ The periodic scan reads the block of the written register after REREAD_DELAY, out of its scan_divider
        and without a shift of its phase: the value set by the unit later, or the old one of a refused write
    """
    monkeypatch.setattr('evok.modbus.client.REREAD_DELAY', 0.05)
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    apply = delayed_unit(client)
    await client.change(lambda: client.write_registers(20, [2]), devices=[])
    await apply(accept)
    counters = [group.f_counter for group in client.cache.groups]
    reads = recorded_reads(client)
    await client.do_scan()                                  # before REREAD_DELAY, the slow group is not due
    await asyncio.sleep(0.06)
    await client.do_scan()
    assert reads == [0, 0, 20]
    assert client.read_registers(20) == [value]
    assert client.cache.groups[2].pins == {}
    expected = counters
    for _ in range(2):
        expected = [divider - 1 if counter == 0 else counter - 1
                    for counter, divider in zip(expected, [g.f_divider for g in client.cache.groups], strict=True)]
    assert [group.f_counter for group in client.cache.groups] == expected


async def test_scan_keeps_the_written_value_until_the_unit_sets_it(monkeypatch):
    """ A block read by every scan: the scan before the unit set the value sent the old one, 2 -> 1 -> 2 """
    monkeypatch.setattr('evok.modbus.client.REREAD_DELAY', 0.05)
    client = make_client(SLOW_BLOCKS, holding={0: 1})
    await client.cache.do_scan(initial=True)
    apply = delayed_unit(client)
    await client.change(lambda: client.write_registers(0, [2]), devices=[])
    await client.do_scan()
    assert client.read_registers(0) == [2]
    await apply()
    await asyncio.sleep(0.06)
    await client.do_scan()
    assert client.read_registers(0) == [2]
    assert client.cache.groups[0].pins == {}


async def test_next_write_renews_the_pin(monkeypatch):
    """ The read due to an earlier write does not overwrite the value of the next one, the unit has not set it """
    monkeypatch.setattr('evok.modbus.client.REREAD_DELAY', 0.05)
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    apply = delayed_unit(client)
    await client.change(lambda: client.write_registers(20, [2]), devices=[])
    await apply()                                           # the unit has 2
    await asyncio.sleep(0.03)
    await client.change(lambda: client.write_registers(20, [3]), devices=[])
    await asyncio.sleep(0.03)                               # the pin of 2 would have expired
    await client.do_scan()
    assert client.read_registers(20) == [3]


async def test_unit_without_the_periodic_scan_shows_the_read(monkeypatch):
    """ Nothing would read the block again, the value read after the change is shown """
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    client.periodic_scan = False
    await client.cache.do_scan(initial=True)
    delayed_unit(client)
    await client.change(lambda: client.write_registers(20, [2]), devices=[])
    assert client.read_registers(20) == [1]
    assert client.cache.groups[2].pins == {}


@pytest.mark.parametrize('alias, error', [('1_02', 'is a circuit of do'), ('all', 'reserved'), ('a b', 'Invalid alias'),
                                          ('taken', 'Duplicate alias')])
async def test_invalid_alias_is_refused_before_the_write(units, alias, error):
    """ The output was switched and then the request failed on its alias """
    client, = await units('1')
    Devices.set_alias('taken', Devices.by_name(DO, '1_02'))
    do = Devices.by_name(DO, '1_01')
    with pytest.raises(ValueError, match=error):
        await set_devices([(do, {'value': 1, 'alias': alias})])
    assert client.mb_client.writes == []
    assert do.alias == ''


async def test_same_alias_twice_in_one_request(units):
    """ Both passed the check against the aliases before the request, the second failed after the first write """
    client1, client2 = await units('1', '2')
    with pytest.raises(ValueError, match='Duplicate alias x'):
        await set_devices([(Devices.by_name(DO, '1_01'), {'value': 1, 'alias': 'x'}),
                           (Devices.by_name(DO, '2_01'), {'value': 1, 'alias': 'x'})])
    assert client1.mb_client.writes == [] and client2.mb_client.writes == []


async def test_alias_moved_in_one_request(units):
    """ An alias released by an earlier assignment was refused as a duplicate """
    await units('1')
    do1, do2 = Devices.by_name(DO, '1_01'), Devices.by_name(DO, '1_02')
    Devices.set_alias('pump', do1)
    await set_devices([(do1, {'alias': 'old_pump'}), (do2, {'alias': 'pump'})])
    assert (do1.alias, do2.alias) == ('old_pump', 'pump')


async def test_alias_released_by_a_later_unit_is_refused(units):
    """ The units are changed in the order of their first assignment: unit 1 takes the alias before unit 2
        releases it, it is refused before any write
    """
    client1, client2 = await units('1', '2')
    do1, do2, do12 = Devices.by_name(DO, '1_01'), Devices.by_name(DO, '2_01'), Devices.by_name(DO, '1_02')
    Devices.set_alias('pump', do2)
    with pytest.raises(ValueError, match='Duplicate alias pump'):
        await set_devices([(do1, {'value': 1}), (do2, {'alias': ''}), (do12, {'alias': 'pump'})])
    assert client1.mb_client.writes == client2.mb_client.writes == [] and do2.alias == 'pump'


@pytest.mark.parametrize('alias', [0, False, 1, ['x'], {'x': 1}])
async def test_alias_which_is_not_a_string_is_refused_before_the_write(units, alias):
    """ 0 passed the check as a reset of the alias, set_alias(0) failed by TypeError after the write """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    with pytest.raises(ValueError, match='Invalid alias'):
        await set_devices([(do, {'value': 1, 'alias': alias})])
    assert client.mb_client.writes == [] and do.alias == ''


async def test_alias_null_keeps_the_alias(units):
    """ null was checked as a reset of the alias, set_alias() keeps it: the alias passed as released to another
        device, the duplicate failed after the write
    """
    client, = await units('1')
    do1, do2 = Devices.by_name(DO, '1_01'), Devices.by_name(DO, '1_02')
    Devices.set_alias('a', do1)
    with pytest.raises(ValueError, match='Duplicate alias a'):
        await set_devices([(do1, {'value': 1, 'alias': None}), (do2, {'value': 1, 'alias': 'a'})])
    assert client.mb_client.writes == [] and (do1.alias, do2.alias) == ('a', '')


async def test_bit_without_a_pin_is_not_pinned():
    client = make_client(SLOW_BLOCKS, holding={20: 0})
    await client.cache.do_scan(initial=True)
    await client.change(lambda: AccessorBit(20, 0b01, pin=False).write_raw(client, 1), devices=[])
    assert client.cache.groups[2].pins == {}


async def test_restart_drops_the_pins(monkeypatch):
    """ A write and a reset of the unit in one change: the unit has its saved settings, the read shows them """
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    delayed_unit(client)

    async def operation():
        await client.write_registers(20, [2])
        await client.write_coil_without_response(1, 1, wait=0)
    await client.change(operation, devices=[])
    assert client.read_registers(20) == [1]
    assert all(not group.pins for group in client.cache.groups)


async def test_counter_is_not_pinned():
    """ The unit counts on after a reset of the counter, the read shows the count, not the written 0 """
    client = make_client(SLOW_BLOCKS, holding={20: 7})
    await client.cache.do_scan(initial=True)
    counter = AccessorU32(20, pin=False)
    assert AccessorU16(20).pin

    async def operation():
        await counter.write_raw(client, 0)
        client.mb_client.holding[20] = 3                    # counted meanwhile
    await client.change(operation, devices=[])
    assert client.read_registers(20) == [3]
    assert client.cache.groups[2].pins == {}


async def test_write_without_a_pin_drops_the_older_pin():
    """ The scan disabled after a pinned write: the older pin would overwrite the next written value """
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    await client.change(lambda: client.write_registers(20, [2]), devices=[])
    client.periodic_scan = False
    await client.change(lambda: client.write_registers(20, [3]), devices=[])
    assert client.read_registers(20) == [3]
    assert client.cache.groups[2].pins == {}


async def test_pin_does_not_set_the_cache_without_cache():
    """ PWM updates the cache after all its writes, a check never sees a partial setting """
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    seen = []

    async def operation():
        await client.write_registers(20, [2], cache=False)
        seen.append(client.read_registers(20))
        client.cache.set_register(20, [2])
    await client.change(operation, devices=[])
    assert seen == [[1]]
    assert client.read_registers(20) == [2]


async def test_long_change_keeps_its_first_writes(monkeypatch):
    """ A change longer than REREAD_DELAY, e.g. retries on a slow bus: the pin of its first write is kept
        until its read
    """
    monkeypatch.setattr('evok.modbus.client.REREAD_DELAY', 0.05)
    client = make_client(SLOW_BLOCKS, holding={20: 1})
    await client.cache.do_scan(initial=True)
    delayed_unit(client)

    async def operation():
        await client.write_registers(20, [2])
        await asyncio.sleep(0.08)
    await client.change(operation, devices=[])
    assert client.read_registers(20) == [2]


async def test_bit_is_written_to_the_pinned_value():
    """ A read-modify-write of a bit after a write the unit has not set yet: the other bit is not lost """
    client = make_client(SLOW_BLOCKS, holding={20: 0})
    await client.cache.do_scan(initial=True)
    delayed_unit(client)
    bit0, bit1 = AccessorBit(20, 0b01), AccessorBit(20, 0b10)
    await client.change(lambda: bit0.write_raw(client, 1), devices=[])
    await client.change(lambda: bit1.write_raw(client, 1), devices=[])
    assert client.mb_client.writes[-1] == ('reg', 20, 0b11)
    assert client.read_registers(20) == [0b11]


async def test_change_with_restart_reads_all_groups():
    client = make_client(SLOW_BLOCKS)
    await client.cache.do_scan(initial=True)
    reads = recorded_reads(client)

    async def operation():
        await client.write_coil_without_response(1, 1, wait=0)
    await client.change(operation, devices=[SimpleNamespace()])
    assert reads == [0, 10, 20, 30]


async def test_change_without_its_groups_reads_the_first_group():
    """ A coil which is not read, on a unit without a group read by every scan: the read after the change finds
        whether the unit responds, a failed write does not leave the unit available
    """
    client = make_client(SLOW_BLOCKS[1:])
    await client.cache.do_scan(initial=True)
    reads = recorded_reads(client)
    await client.change(lambda: client.mb_client.write_single_coil(0, 1), devices=[SimpleNamespace()])
    assert reads == [10]

    async def failed_write():
        client.mb_client.connected = False
        raise TimeoutError('no response')
    with pytest.raises(UnitCommunicationError):
        await client.change(failed_write, devices=[SimpleNamespace()])
    assert client.comm() == 'error'


async def test_state_of_other_mode_is_read_after_the_change():
    """ The value of the resistance of an AO is read after the change of its mode, also in a slow block """
    client = make_client([{'start_reg': 0, 'count': 1, 'scan_divider': 1},
                          {'start_reg': 2, 'count': 3, 'scan_divider': 50}])
    ao = AnalogOutputBrain('x', client, 0, regmode=4, reg_res=2)
    assert {(0, False), (1, False), (2, False), (3, False)} <= device_registers(ao)


async def test_scan_does_not_check_the_devices_between_the_writes_of_a_change():
    """ A scan with no group to read during a change: the cache has the first write, the change checks the
        devices after its writes
    """
    transport = BusTransport(SlowBus(), probe_timeout=1.0, wait_between_requests=0.0, wait_after_connect=0.0,
                             retry_on_device_busy=False, retry_on_device_failure=False)
    mb = AsyncModbusClient(transport, unit_id=1)
    client = Client('1', mb, ModbusCacheMap(SLOW_BLOCKS[1:3], mb))
    await client.cache.do_scan(initial=True)
    checks = []
    check = client._check_devices

    async def recorded():
        checks.append(client.read_registers(10) + client.read_registers(20))
        await check()
    client._check_devices = recorded

    async def operation():
        await client.write_registers(10, [1])
        await client.do_scan()                              # the periodic scan, no group to read
        await client.check_devices()
        await client.write_registers(20, [1])
    await client.change(operation, devices=[])
    assert len(checks) == 1                                 # not [1, 0] between the writes


async def test_set_devices_reads_the_group_of_the_device(units):
    """ A digital output: its coil, the register of its state in the block read by every scan """
    client, = await units('1')
    coil_drives_register(client, 0, 1, 0b01)
    reads = recorded_reads(client)
    await set_devices([(Devices.by_name(DO, '1_01'), {'value': 1})])
    fast = [group.address for group in client.cache.groups + client.cache.igroups if group.f_divider == 1]
    assert reads == fast
    assert Devices.by_name(DO, '1_01').full()['value'] == 1


async def test_unavailable_unit_is_not_changed(units):
    client, = await units('1')
    client.cache.scan_error = TimeoutError('no response')
    do = Devices.by_name(DO, '1_01')
    with pytest.raises(UnitUnavailable, match='TimeoutError: no response'):
        await set_devices([(do, {'value': 1})])
    assert client.mb_client.writes == []
    # the alias does not write the unit
    state, = await set_devices([(do, {'alias': 'lamp'})])
    assert state['alias'] == 'lamp'


async def test_unit_without_periodic_scan_is_read_before_it_is_refused(units):
    """ A failed scan after a change refused all next changes of a unit without scan_enabled, nothing read it again """
    client, = await units('1')
    client.periodic_scan = False
    do = Devices.by_name(DO, '1_01')
    client.cache.scan_error = TimeoutError('no response')
    _state, = await set_devices([(do, {'value': 1})])        # the unit responds again
    assert client.cache.scan_error is None and client.mb_client.writes == [('coil', 0, 1)]
    client.mb_client.connected = False
    client.cache.scan_error = TimeoutError('no response')
    with pytest.raises(UnitUnavailable):
        await set_devices([(do, {'value': 0})])
    assert client.mb_client.writes == [('coil', 0, 1)]


async def test_unavailable_unit_has_its_name(l0306):
    """ The unit was named by its transport, not by its name in the configuration """
    scanner = ModbusScanner(AsyncSmartTransport(AsyncTcpTransport('127.0.0.1', 502)), 'IAQ', 50, True, l0306,
                            unit_id=1)
    scanner.cache.scan_error = TimeoutError('no response')
    with pytest.raises(UnitUnavailable, match=r"Unit 'IAQ' \(TCP:127.0.0.1:1\) is not available: "
                                              r"TimeoutError: no response"):
        await scanner.client.change(lambda: asyncio.sleep(0))


async def test_failed_request_of_change_is_a_communication_error(units):
    """ A failed write was an internal error with a traceback, HTTP 500 """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')

    async def no_response(*args):
        raise RequestRetryFailedError('no response')
    client.mb_client.write_single_coil = no_response
    with pytest.raises(UnitCommunicationError, match="RequestRetryFailedError: no response") as error:
        await set_devices([(do, {'value': 1})])
    assert client_error(error.value)[1] == 503
    with pytest.raises(UnitUnavailableError):
        await create_response(SimpleNamespace(method='output_set', params=['1_01', 1]), Handler.__new__(Handler))


async def test_alias_is_sent_as_event(units, events):
    """ A new alias of a device on a Modbus unit was not sent, check_new_data() does not compare it """
    client, = await units('1')
    do, nv_save = Devices.by_name(DO, '1_01'), Devices.by_name(NV_SAVE, '1')
    await set_devices([(do, {'alias': 'lamp'}), (nv_save, {'alias': 'save'})])     # also without check_new_data()
    assert client.mb_client.writes == []                    # the unit is not written nor read
    assert [proxy.changeset for proxy in events] == [[do, nv_save]]
    events.clear()
    coil_drives_register(client, 0, 1, 0b01)
    await set_devices([(do, {'value': 1, 'alias': 'light'})])
    assert [proxy.changeset for proxy in events] == [[do]]   # one event of the value and the alias
    events.clear()
    Devices.set_alias('', do)                               # e.g. deleted by the device run
    await client.do_scan()
    assert [proxy.changeset for proxy in events] == [[do]]
    assert 'alias' not in events[0].full()[0]


async def test_scan_waits_for_the_change(units):
    """ The periodic scan read the registers between the writes of a change """
    client, = await units('1')
    release = asyncio.Event()
    order = []

    async def operation():
        order.append('change')
        await release.wait()
    change = asyncio.create_task(client.change(operation))
    await asyncio.sleep(0)
    do_scan = client._scan

    async def periodic(read=None):
        order.append('scan' if read is None else 'scan of the change')
        return await do_scan(read)
    client._scan = periodic
    periodic_scan = asyncio.create_task(client.do_scan())
    await asyncio.sleep(0.01)
    assert not periodic_scan.done()
    release.set()
    await asyncio.gather(change, periodic_scan)
    assert order == ['change', 'scan of the change', 'scan']


async def test_units_are_changed_one_after_another(units):
    """ The states are in the order of the assignments, a unit is changed and read once """
    client1, client2 = await units('1', '2')
    changes = []
    for client in (client1, client2):
        change = client.change

        async def counted(operation, *args, _client=client, _change=change, **kwargs):
            changes.append(_client)
            return await _change(operation, *args, **kwargs)
        client.change = counted
    assignments = [(Devices.by_name(DO, '2_01'), {'value': 1}), (Devices.by_name(DO, '1_01'), {'value': 1}),
                   (Devices.by_name(DO, '2_02'), {'value': 1})]
    states = await set_devices(assignments)
    assert [state['circuit'] for state in states] == ['2_01', '1_01', '2_02']
    assert changes == [client2, client1]


async def test_error_keeps_the_states_done_before_it(units):
    _client1, _client2, client3 = await units('1', '2', '3')
    assignments = [(Devices.by_name(DO, '1_01'), {'value': 1}),
                   (Devices.by_name(DO, '2_01'), {'value': 1}),
                   (Devices.by_name(DO, '2_02'), {'pwm_duty': 150}),     # fails in set()
                   (Devices.by_name(DO, '3_01'), {'value': 1})]
    states = {}
    with pytest.raises(ValueError):
        await set_devices(assignments, states)
    assert sorted(states) == [0, 1]
    assert client3.mb_client.writes == []


async def test_pulse_ends_under_the_lock_also_on_unavailable_unit(units, events):
    client, = await units('1')
    coil_drives_register(client, 0, 1, 0b01)
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.01)
    client.cache.scan_error = TimeoutError('no response')
    events.clear()
    await asyncio.sleep(0.05)
    assert client.mb_client.coils[0] == 0
    assert do.value == 0 and events                         # read at once, not by the next scan


async def test_pulse_end_does_not_overwrite_newer_pulse(units):
    """ The end of the pulse waiting for the lock before a new pulse is written first, the new pulse is not
        overwritten by it; the old pulse is cancelled after the write of the new one
    """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.02)
    await client.lock.acquire()                             # e.g. a change of another output
    await asyncio.sleep(0.05)                               # the pulse ends and waits for the lock
    newer = asyncio.create_task(start_pulse(do, 1, 10))
    await asyncio.sleep(0.01)
    client.lock.release()
    await newer
    await asyncio.sleep(0.01)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0), ('coil', 0, 1)]
    assert sequencer.sequence(do).steps[0].delay == 10


async def test_new_pulse_waiting_for_the_lock_cancels_the_next_step(units):
    """ The old pulse ends after the write of the new one, its end does not overwrite it """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.05)
    await client.lock.acquire()
    newer = asyncio.create_task(start_pulse(do, 1, 10))     # waits for the lock before the end of the old pulse
    await asyncio.sleep(0.01)
    client.lock.release()
    await newer
    await asyncio.sleep(0.08)                               # after the end of the old pulse
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 1)]
    assert sequencer.sequence(do).steps[0].delay == 10


async def test_pulse_cancelled_after_its_write_keeps_its_end(units):
    """ The task of a new pulse cancelled while the unit is read after the write, e.g. at the shutdown:
        the pulse runs, it was started after the read and the output stayed on without its end
    """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 10)
    release = asyncio.Event()
    read = client.mb_client.read_holding_registers

    async def slow_read(address, quantity=1):
        await release.wait()
        return await read(address, quantity)
    client.mb_client.read_holding_registers = slow_read
    newer = asyncio.create_task(start_pulse(do, 1, 0.05))
    await asyncio.sleep(0.01)                               # written, the unit is read
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 1)]
    newer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await newer
    assert sequencer.sequence(do).steps[0].delay == 0.05
    release.set()
    await asyncio.sleep(0.1)
    assert client.mb_client.writes[-1] == ('coil', 0, 0)
    assert not sequencer.is_running(do)


async def test_failed_pulse_leaves_the_running_one(units):
    """ A new pulse refused by an unavailable unit: the running pulse writes its end, the output does not stay on """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.05)
    client.cache.scan_error = TimeoutError('no response')
    with pytest.raises(UnitUnavailable):
        await start_pulse(do, 1, 10)
    assert sequencer.sequence(do).steps[0].delay == 0.05
    await asyncio.sleep(0.08)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]
    assert not sequencer.is_running(do)


async def slow_coil(client):
    """ The writes of the coils wait for the returned event, the event of the started write is .started """
    release, started = asyncio.Event(), asyncio.Event()
    write = client.mb_client.write_single_coil

    async def slow(address, value):
        started.set()
        await release.wait()
        await write(address, value)
    client.mb_client.write_single_coil = slow
    release.started = started
    return release


async def test_cancel_does_not_interrupt_the_write_of_a_step(units):
    """ The task of the step was cancelled in the middle of its Modbus request """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.01)
    release = await slow_coil(client)
    await asyncio.wait_for(release.started.wait(), 1)       # the end of the pulse is being written
    sequencer.cancel(do)
    release.set()
    await asyncio.sleep(0.02)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]      # the write was finished
    assert not sequencer.is_running(do)


async def test_finish_all_waits_for_the_write_of_a_step(units):
    """ The last step left the running sequences before its write, finish_all() did not wait for it """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.01)
    release = await slow_coil(client)
    await asyncio.wait_for(release.started.wait(), 1)
    finish = asyncio.create_task(sequencer.finish_all())
    await asyncio.sleep(0.01)
    assert not finish.done()                                # waits for the write
    release.set()
    await finish
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]


async def test_finish_all_writes_the_final_state_after_a_failed_last_step(units):
    """ The end of a pulse being written when Evok stops fails: its final state is written, the relay stayed on """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.01)
    release, started = asyncio.Event(), asyncio.Event()
    write = client.mb_client.write_single_coil
    failures = [ConnectionError('noise')]

    async def flaky(address, value):
        started.set()
        await release.wait()
        if failures:
            raise failures.pop()
        await write(address, value)
    client.mb_client.write_single_coil = flaky
    await asyncio.wait_for(started.wait(), 1)
    finish = asyncio.create_task(sequencer.finish_all())
    await asyncio.sleep(0.01)
    release.set()
    await finish
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]


async def test_nv_save_is_changed_under_the_lock(units):
    client, = await units('1')
    nv_save = Devices.by_name(NV_SAVE, '1')
    await client.lock.acquire()
    change = asyncio.create_task(set_devices([(nv_save, {'value': 1})]))
    await asyncio.sleep(0.01)
    assert client.mb_client.writes == []
    client.lock.release()
    await change
    assert client.mb_client.writes == [('coil', 1003, 1)]


def test_unavailable_unit_is_503():
    assert client_error(UnitUnavailable('Unit x is not available'))[1] == 503


async def test_rpc_unavailable_unit(units):
    client, = await units('1')
    client.cache.scan_error = TimeoutError('no response')
    with pytest.raises(UnitUnavailableError):
        await create_response(SimpleNamespace(method='input_set', params=['1_01', 10]),
                              Handler.__new__(Handler))
    assert Devices.by_name(DI, '1_01').debounce != 10


def restarting_unit(client, coil, error):
    """ The unit restarts after the write of the coil, it does not respond """
    writes = []
    write = client.mb_client.write_single_coil

    async def restart(address, value):
        if address == coil:
            writes.append((address, value))
            raise error
        await write(address, value)
    client.mb_client.write_single_coil = restart
    return writes


@pytest.mark.parametrize('error', [TimeoutError('Response timeout after 0.5 seconds'),
                                   CRCError('CRC error', response_bytes=b'\x0f\x05')])
async def test_reset_of_a_unit_without_a_response(units, monkeypatch, error):
    """ The reset was a 503 error and it was sent twice by the retry """
    from evok.modbus import client as client_module
    monkeypatch.setattr(client_module, 'RESTART_WAIT', 0.02)
    client, = await units('1')
    writes = restarting_unit(client, 1002, error)
    start = asyncio.get_running_loop().time()
    state, = await set_devices([(Devices.by_name(WATCHDOG, '1'), {'reset': 1})])
    assert writes == [(1002, 1)] and state['dev'] == 'wd'
    assert asyncio.get_running_loop().time() - start >= 0.02       # waited for the restart before the read


async def test_nv_save_of_a_unit_without_a_response(units, monkeypatch):
    from evok.modbus import client as client_module
    monkeypatch.setattr(client_module, 'RESTART_WAIT', 0)
    client, = await units('1')
    writes = restarting_unit(client, 1003, TimeoutError('Response timeout'))
    state, = await set_devices([(Devices.by_name(NV_SAVE, '1'), {'value': 1})])
    assert writes == [(1003, 1)] and state['value'] == 1


async def test_reset_refused_by_the_unit_is_an_error(units, monkeypatch):
    """ An exception response is not a restart """
    from tmodbus.exceptions import IllegalDataAddressError

    from evok.modbus import client as client_module
    monkeypatch.setattr(client_module, 'RESTART_WAIT', 0)
    client, = await units('1')
    restarting_unit(client, 1002, IllegalDataAddressError(5))
    with pytest.raises(UnitCommunicationError):
        await set_devices([(Devices.by_name(WATCHDOG, '1'), {'reset': 1})])


async def test_write_coil_without_response_reports_the_response(units, monkeypatch):
    from evok.modbus import client as client_module
    monkeypatch.setattr(client_module, 'RESTART_WAIT', 0)
    client, = await units('1')
    assert await client.write_coil_without_response(1002, 1) is True
    restarting_unit(client, 1002, TimeoutError())
    assert await client.write_coil_without_response(1002, 1) is False


# ---- #201: comm and last_comm of the devices ----

@pytest.mark.parametrize('error, comm', [
    (None, 'ok'),
    (TimeoutError('Response timeout'), 'timeout'),
    (CRCError('CRC error', response_bytes=b'\x01'), 'error'),
])
async def test_comm_of_a_unit(units, error, comm):
    client, = await units('1')
    client.cache.scan_error = error
    assert client.comm() == comm


async def test_comm_of_a_timeout_of_the_retries(units):
    """ The root cause of the error of tmodbus decides, a RequestRetryFailedError of a timeout is a timeout """
    client, = await units('1')
    error = RequestRetryFailedError('Failed after 2 attempts')
    error.__cause__ = TimeoutError('Response timeout after 0.5 seconds')
    client.cache.scan_error = error
    assert client.comm() == 'timeout'


def fail_reads(client, error):
    async def fail(*args, **kwargs):
        raise error
    client.mb_client.read_holding_registers = fail
    client.mb_client.read_input_registers = fail


async def test_lost_unit_sends_all_its_devices_once(units, events):
    client, = await units('1')
    di = Devices.by_name(DI, '1_01')
    assert (di.full()['comm'], di.full()['last_comm'] >= 0) == ('ok', True)
    reads = client.mb_client.read_holding_registers, client.mb_client.read_input_registers
    fail_reads(client, TimeoutError('Response timeout'))
    events.clear()
    assert not await client.do_scan()
    assert not await client.do_scan()                       # the same comm, no event
    lost, = [proxy.changeset for proxy in events]
    assert len(lost) == len(set(client.eventable_devices + client.devices)) and di in lost
    assert di.full()['comm'] == 'timeout' and di.full()['value'] is not None      # the last known value
    client.mb_client.read_holding_registers, client.mb_client.read_input_registers = reads
    events.clear()
    assert await client.do_scan()
    recovered, = [proxy.changeset for proxy in events]
    assert len(recovered) == len(lost) and di.full()['comm'] == 'ok'
