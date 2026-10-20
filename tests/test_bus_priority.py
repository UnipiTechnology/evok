""" The priority of the changes on a bus (#267): the requests of a unit with a waiting change go first """
import asyncio
import time

import pytest
from tmodbus import AsyncModbusClient
from tmodbus.pdu import ReadHoldingRegistersPDU, ReadInputRegistersPDU

from evok.modbus.cache import ModbusCacheMap
from evok.modbus.client import Client
from evok.modbus.transport import _REQUEST_UNIT, BusTransport, PriorityLock

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


# ---- PriorityLock ----

async def _hold(lock, order, name, unit=None, hold=0.0):
    _REQUEST_UNIT.set(unit)
    async with lock:
        order.append(name)
        await asyncio.sleep(hold)


async def test_waiters_of_one_priority_in_their_order():
    lock, order = PriorityLock(lambda unit: False), []
    tasks = [asyncio.create_task(_hold(lock, order, i, hold=0.01)) for i in range(4)]
    await asyncio.gather(*tasks)
    assert order == [0, 1, 2, 3]
    assert not lock.locked()


async def test_high_priority_goes_first():
    lock, order = PriorityLock(lambda unit: unit == 9), []
    first = asyncio.create_task(_hold(lock, order, 'first', hold=0.05))
    await asyncio.sleep(0)
    tasks = [asyncio.create_task(_hold(lock, order, name, unit)) for name, unit in
             (('a', 1), ('b', 2), ('high', 9), ('c', 3))]
    await asyncio.gather(first, *tasks)
    assert order == ['first', 'high', 'a', 'b', 'c']


async def test_priority_raised_while_waiting():
    """ The priority is given at the release, a request which waits already goes first after the raise """
    high = set()
    lock, order = PriorityLock(lambda unit: unit in high), []
    first = asyncio.create_task(_hold(lock, order, 'first', hold=0.05))
    await asyncio.sleep(0)
    tasks = [asyncio.create_task(_hold(lock, order, name, unit)) for name, unit in (('a', 1), ('b', 2))]
    await asyncio.sleep(0.01)
    high.add(2)
    await asyncio.gather(first, *tasks)
    assert order == ['first', 'b', 'a']


async def test_cancelled_waiter_is_skipped():
    lock, order = PriorityLock(lambda unit: False), []
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
    lock, order = PriorityLock(lambda unit: False), []
    await lock.acquire()
    waiter = asyncio.create_task(_hold(lock, order, 'cancelled'))
    last = asyncio.create_task(_hold(lock, order, 'last'))
    await asyncio.sleep(0)
    lock.release()              # handed to the first waiter, it did not run yet
    waiter.cancel()
    await asyncio.gather(last)
    assert order == ['last']
    assert not lock.locked()


def test_release_of_unlocked_lock():
    with pytest.raises(RuntimeError):
        PriorityLock(lambda unit: False).release()


# ---- BusTransport ----

async def _scan(transport, unit_id, stop):
    """ A unit scanned as fast as possible, its requests always wait in the queue of the bus """
    client = AsyncModbusClient(transport, unit_id=unit_id)
    while not stop.is_set():
        await client.read_holding_registers(0, 1)


async def test_request_of_prioritized_unit_goes_before_the_scans():
    base = SlowBus()
    transport, stop = bus_transport(base), asyncio.Event()
    scans = [asyncio.create_task(_scan(transport, unit, stop)) for unit in range(1, 7)]
    await asyncio.sleep(0.05)
    with transport.priority(7):
        before = len(base.requests)
        await AsyncModbusClient(transport, unit_id=7).write_single_coil(0, True)
    stop.set()
    await asyncio.gather(*scans)
    # the requests of the scans done before the write: only the one sent when the write came
    done = base.requests.index((7, 'WriteSingleCoilPDU')) - before
    assert done <= 1


async def test_priority_of_unit_ends_after_the_change():
    transport = bus_transport(SlowBus())
    with transport.priority(3), transport.priority(3):
        assert transport._priority_units[3] == 2
    assert 3 not in transport._priority_units


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
        client._priority = lambda: transport.priority(None)     # no unit is prioritized
    start = time.monotonic()
    await client.change(lambda: client.mb_client.write_single_coil(0, True))
    latency = time.monotonic() - start
    stop.set()
    await asyncio.gather(*scans)
    return latency


async def test_change_does_not_wait_for_the_scans_of_the_other_units():
    """ A write and the read of 3 blocks, after the rest of the running scan of the unit: about 7 requests;
        without the priority each of them waits behind the scans of the other 5 units
    """
    latency = await change_latency(prioritized=True)
    without = await change_latency(prioritized=False)
    assert latency < 9 * REQUEST_TIME, latency
    assert without > 2 * latency, (latency, without)
