""" The priority of the changes on a bus (#267): the requests of a change go first, the scan of its unit waits """
import asyncio
import contextlib
import contextvars
import time

import pytest
from tmodbus import AsyncModbusClient
from tmodbus.pdu import ReadHoldingRegistersPDU, ReadInputRegistersPDU

from evok.modbus.cache import ModbusCacheMap
from evok.modbus.client import Client
from evok.modbus.transport import _REQUEST_UNIT, BusTransport, SessionLock

REQUEST_TIME = 0.01  # s, a request of the slow fake bus


class SlowBus:
    """ The base transport of a bus, each request takes REQUEST_TIME, the order of the requests is recorded """

    def __init__(self):
        self.requests = []

    def is_open(self):
        return True

    async def open(self):
        pass

    async def close(self):
        pass

    async def send_and_receive(self, unit_id, pdu):
        await asyncio.sleep(REQUEST_TIME)
        self.requests.append((unit_id, type(pdu).__name__))
        if isinstance(pdu, (ReadHoldingRegistersPDU, ReadInputRegistersPDU)):
            return [0] * pdu.quantity
        return True


def bus_transport(base):
    return BusTransport(base, probe_timeout=1.0, wait_between_requests=0.0, wait_after_connect=0.0,
                        retry_on_device_busy=False, retry_on_device_failure=False)


# ---- SessionLock ----

async def _hold(lock, order, name, unit=None, hold=0.0, session=False):
    _REQUEST_UNIT.set(unit)
    with lock.session(unit) if session else contextlib.nullcontext():
        async with lock:
            order.append(name)
            await asyncio.sleep(hold)


async def test_waiters_without_session_in_their_order():
    lock, order = SessionLock(), []
    tasks = [asyncio.create_task(_hold(lock, order, i, unit=i, hold=0.01)) for i in range(4)]
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2, 3]
    assert not lock.locked()


async def test_request_of_session_goes_first():
    lock, order = SessionLock(), []
    first = asyncio.create_task(_hold(lock, order, 'first', hold=0.05))
    await asyncio.sleep(0)
    tasks = [asyncio.create_task(_hold(lock, order, name, unit, session=unit == 9)) for name, unit in
             (('a', 1), ('b', 2), ('session', 9), ('c', 3))]
    await asyncio.gather(first, *tasks)
    assert order == ['first', 'session', 'a', 'b', 'c']


async def test_other_request_of_unit_waits_for_its_session():
    """ The scan of the unit waits until the change ends, the other units use the bus meanwhile """
    lock, order = SessionLock(), []
    _REQUEST_UNIT.set(1)
    with lock.session(1):
        async with lock:
            order.append('write')
        # the scans run out of the session, not in a task created in it
        scan = asyncio.create_task(_hold(lock, order, 'scan of 1', unit=1), context=contextvars.Context())
        other = asyncio.create_task(_hold(lock, order, 'scan of 2', unit=2), context=contextvars.Context())
        await asyncio.sleep(0.01)                       # the change computes, it has no request
        async with lock:
            order.append('read')
    await asyncio.gather(scan, other)
    assert order == ['write', 'scan of 2', 'read', 'scan of 1']
    assert not lock.locked()


async def test_other_request_of_unit_goes_before_its_next_session():
    """ A stream of the changes of a unit does not stop its scan """
    lock, order = SessionLock(), []
    first = asyncio.create_task(_hold(lock, order, 'change 1', unit=1, hold=0.02, session=True))
    await asyncio.sleep(0)
    scan = asyncio.create_task(_hold(lock, order, 'scan', unit=1))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(_hold(lock, order, 'change 2', unit=1, session=True))
    await asyncio.gather(first, scan, second)
    assert order == ['change 1', 'scan', 'change 2']


async def test_task_created_in_session_is_not_in_it_after_it():
    lock, order = SessionLock(), []
    _REQUEST_UNIT.set(1)
    with lock.session(1):
        later = asyncio.create_task(_hold(lock, order, 'pulse', unit=1, hold=0.0))
    await asyncio.sleep(0)
    await lock.acquire()
    other = asyncio.create_task(_hold(lock, order, 'scan', unit=2))
    await asyncio.sleep(0)
    lock.release()
    await asyncio.gather(later, other)
    assert order == ['pulse', 'scan'] or order == ['scan', 'pulse']
    assert not lock.locked()


async def test_cancelled_waiter_is_skipped():
    lock, order = SessionLock(), []
    first = asyncio.create_task(_hold(lock, order, 'first', hold=0.05))
    await asyncio.sleep(0)
    cancelled = asyncio.create_task(_hold(lock, order, 'cancelled'))
    last = asyncio.create_task(_hold(lock, order, 'last'))
    await asyncio.sleep(0.01)
    cancelled.cancel()
    await asyncio.gather(first, last)
    assert order == ['first', 'last']
    assert not lock.locked()


async def test_lock_handed_to_cancelled_waiter_goes_on():
    """ A waiter cancelled after the release handed it the lock passes it to the next one """
    lock, order = SessionLock(), []
    await lock.acquire()
    waiter = asyncio.create_task(_hold(lock, order, 'cancelled'))
    last = asyncio.create_task(_hold(lock, order, 'last'))
    await asyncio.sleep(0)
    lock.release()
    await asyncio.sleep(0)      # handed to the first waiter, it did not run yet
    waiter.cancel()
    await asyncio.gather(last)
    assert order == ['last']
    assert not lock.locked()


def test_release_of_unlocked_lock():
    with pytest.raises(RuntimeError):
        SessionLock().release()


# ---- BusTransport ----

async def _scan(transport, unit_id, stop):
    """ A unit scanned as fast as possible, its requests always wait in the queue of the bus """
    client = AsyncModbusClient(transport, unit_id=unit_id)
    while not stop.is_set():
        await client.read_holding_registers(0, 1)


async def test_request_of_session_goes_before_the_scans():
    base = SlowBus()
    transport, stop = bus_transport(base), asyncio.Event()
    scans = [asyncio.create_task(_scan(transport, unit, stop)) for unit in range(1, 7)]
    await asyncio.sleep(0.05)
    with transport.session(7):
        before = len(base.requests)
        await AsyncModbusClient(transport, unit_id=7).write_single_coil(0, True)
    stop.set()
    await asyncio.gather(*scans)
    # the requests of the scans done before the write: only the one sent when the write came
    done = base.requests.index((7, 'WriteSingleCoilPDU')) - before
    assert done <= 1


async def test_session_of_unit_ends_after_the_change():
    transport = bus_transport(SlowBus())
    with transport.session(3), transport.session(3):
        assert transport._communication_lock._sessions[3] == 2
    assert 3 not in transport._communication_lock._sessions


# ---- the change of a unit on a busy bus ----

BLOCKS = [{'start_reg': 0, 'count': 4, 'scan_divider': 1},
          {'start_reg': 100, 'count': 4, 'scan_divider': 1},
          {'start_reg': 200, 'count': 4, 'scan_divider': 1}]


def unit(transport, unit_id):
    mb = AsyncModbusClient(transport, unit_id=unit_id)
    return Client(str(unit_id), mb, ModbusCacheMap(BLOCKS, mb))


async def _scan_unit(client, stop):
    while not stop.is_set():
        await client.do_scan()


async def change_latency(prioritized: bool, units: int = 6) -> float:
    transport, stop = bus_transport(SlowBus()), asyncio.Event()
    clients = [unit(transport, unit_id) for unit_id in range(1, units + 1)]
    scans = [asyncio.create_task(_scan_unit(client, stop)) for client in clients]
    await asyncio.sleep(0.1)
    client = clients[0]
    if not prioritized:
        client._bus = None                                      # the change without a session
    start = time.monotonic()
    await client.change(lambda: client.mb_client.write_single_coil(0, True))
    latency = time.monotonic() - start
    stop.set()
    await asyncio.gather(*scans)
    return latency


async def test_change_does_not_wait_for_the_scans():
    """ A write and the read of 3 blocks after the request on the bus: about 5 requests, the change does not
        wait for the scan of its unit; without the session each of them waits behind the scans of the other units
    """
    latency = await change_latency(prioritized=True)
    without = await change_latency(prioritized=False)
    assert latency < 7 * REQUEST_TIME, latency
    assert without > 2 * latency, (latency, without)


async def test_scan_does_not_read_the_unit_between_the_writes_of_a_change():
    base = SlowBus()
    transport, stop = bus_transport(base), asyncio.Event()
    clients = [unit(transport, unit_id) for unit_id in range(1, 4)]
    scans = [asyncio.create_task(_scan_unit(client, stop)) for client in clients]
    await asyncio.sleep(0.05)
    client = clients[0]

    async def operation():
        await client.mb_client.write_single_coil(0, True)
        await asyncio.sleep(3 * REQUEST_TIME)                   # e.g. the computation of the next value
        await client.mb_client.write_single_coil(1, True)
    before = len(base.requests)
    await client.change(operation)
    stop.set()
    await asyncio.gather(*scans)
    requests = base.requests[before:]
    first, second = requests.index((1, 'WriteSingleCoilPDU')), len(requests) - 1 - requests[::-1].index(
        (1, 'WriteSingleCoilPDU'))
    between = requests[first + 1:second]
    assert between and all(unit_id != 1 for unit_id, _ in between)  # the other units used the bus


async def test_stream_of_changes_does_not_stop_the_scans():
    """ After each change one waiting scan request of another unit goes first, also of the changed unit """
    base = SlowBus()
    transport, stop = bus_transport(base), asyncio.Event()
    clients = [unit(transport, unit_id) for unit_id in range(1, 5)]
    scans = [asyncio.create_task(_scan_unit(client, stop)) for client in clients]
    client = clients[0]

    async def changes():
        while not stop.is_set():
            await client.change(lambda: client.mb_client.write_single_coil(0, True))
    writers = [asyncio.create_task(changes()) for _ in range(2)]
    await asyncio.sleep(0.05)
    before = len(base.requests)
    await asyncio.sleep(60 * REQUEST_TIME)
    requests = base.requests[before:]
    stop.set()
    await asyncio.gather(*scans, *writers)
    changes_done = requests.count((1, 'WriteSingleCoilPDU'))
    # a change is a write and the read of 3 blocks, then a scan request of unit 1 and of another unit
    assert changes_done >= 8, changes_done
    for unit_id in range(2, 5):
        assert sum(1 for request in requests if request[0] == unit_id) >= changes_done // 3 - 1, unit_id


async def test_turn_of_cancelled_scan_is_dropped():
    """ The scan of the unit waiting for its turn after a session is cancelled, e.g. the unit stops its scan:
        the next scan of the unit waits for the next session
    """
    lock, order = SessionLock(), []
    await lock.acquire()                        # a request of another unit on the bus
    scan = asyncio.create_task(_hold(lock, order, 'cancelled scan', unit=1), context=contextvars.Context())
    await asyncio.sleep(0)
    with lock.session(1):                       # a change of unit 1 ends while its scan waits
        pass
    assert 1 in lock._turns
    scan.cancel()
    await asyncio.sleep(0)
    lock.release()
    assert 1 not in lock._turns

    _REQUEST_UNIT.set(1)
    with lock.session(1):
        async with lock:
            order.append('write')
        later = asyncio.create_task(_hold(lock, order, 'scan', unit=1), context=contextvars.Context())
        await asyncio.sleep(0.01)
        async with lock:
            order.append('read')
    await later
    assert order == ['write', 'read', 'scan']


# ---- the serial buses held by the save of the flash of a unit ----

class TimedBus(SlowBus):
    """ The times of the ends of the requests """

    def __init__(self):
        super().__init__()
        self.times = []

    async def send_and_receive(self, unit_id, pdu):
        result = await super().send_and_receive(unit_id, pdu)
        self.times.append(time.monotonic())
        return result


@pytest.mark.parametrize('held', [True, False])
async def test_save_of_unit_holds_its_serial_bus(monkeypatch, held):
    """ No request on the serial port served by the unit from before the write of the coil (nv_save, reset)
        until SERIAL_HOLD_TIME after it, the request being sent ends first
    """
    monkeypatch.setattr('evok.modbus.client.SERIAL_HOLD_TIME', 10 * REQUEST_TIME)
    monkeypatch.setattr('evok.modbus.client.RESTART_WAIT', 0)
    serial, local_bus = TimedBus(), TimedBus()
    rtu, stop = bus_transport(serial), asyncio.Event()
    scans = [asyncio.create_task(_scan(rtu, unit_id, stop)) for unit_id in (1, 2)]
    local = unit(bus_transport(local_bus), 1)
    local.serial_buses = [rtu] if held else []
    await asyncio.sleep(0.05)
    await local.change(lambda: local.write_coil_without_response(5, 1), devices=[])
    stop.set()
    await asyncio.gather(*scans)
    write = local_bus.times[0]                  # the end of the write, it took REQUEST_TIME
    during = [t for t in serial.times if write - REQUEST_TIME / 2 < t < write + 10 * REQUEST_TIME]
    assert (not during) if held else during
