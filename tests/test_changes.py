""" The changes of the devices of a Modbus unit under its lock, Client.change() and set_devices() """
import asyncio
from types import SimpleNamespace

import pytest
from conftest import make_client, scan
from tmodbus import AsyncSmartTransport, AsyncTcpTransport
from tmodbus.exceptions import CRCError, RequestRetryFailedError

from evok import devents
from evok.blocks import sequencer, start_pulse
from evok.devices import DI, DO, NV_SAVE, WATCHDOG, Devices
from evok.errors import UnitCommunicationError, UnitUnavailable
from evok.handlers_base import client_error
from evok.modbus import set_devices
from evok.modbus.builder import IOParser
from evok.modbus.scanner import ModbusScanner
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
    state, = await set_devices([(do, {'value': 1})])        # the unit responds again
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

    async def periodic(all_groups=False):
        order.append('scan' if not all_groups else 'scan of the change')
        return await do_scan(all_groups)
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
    client1, client2, client3 = await units('1', '2', '3')
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
    """ The end of the pulse waiting for the lock is cancelled by a new pulse, it did not overwrite its value """
    client, = await units('1')
    do = Devices.by_name(DO, '1_01')
    await start_pulse(do, 1, 0.02)
    await client.lock.acquire()                             # e.g. a scan
    await asyncio.sleep(0.05)                               # the pulse ends and waits for the lock
    newer = asyncio.create_task(start_pulse(do, 1, 10))
    await asyncio.sleep(0.01)
    client.lock.release()
    await newer
    await asyncio.sleep(0.01)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 1)]
    assert sequencer.is_running(do)


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

