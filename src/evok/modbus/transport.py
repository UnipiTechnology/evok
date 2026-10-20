import asyncio
import collections
import contextlib
import contextvars
import time
from collections.abc import Callable

from tmodbus import AsyncSmartTransport

# the unit id of the request of the running task, the key of its priority in the lock of the bus
_REQUEST_UNIT: contextvars.ContextVar[int | None] = contextvars.ContextVar("request_unit", default=None)


class PriorityLock:
    """An asyncio lock whose release hands it to the first waiter of the high priority, else to the first waiter

    The priority of a waiter is the priority of its key at the release, a waiter which waits already gets
    the high priority when it is raised, e.g. the request of the running scan of a unit with a waiting change.
    The key of a waiter is the unit id of its request (_REQUEST_UNIT), tmodbus uses the lock by async with.
    """

    def __init__(self, high: Callable[[int | None], bool]):
        self._high = high
        self._locked = False
        self._waiters: collections.deque[tuple[asyncio.Future, int | None]] = collections.deque()

    def locked(self) -> bool:
        return self._locked

    async def acquire(self) -> bool:
        if not self._locked and not any(not waiter[0].done() for waiter in self._waiters):
            self._locked = True
            return True
        waiter = (asyncio.get_running_loop().create_future(), _REQUEST_UNIT.get())
        self._waiters.append(waiter)
        try:
            await waiter[0]
        except asyncio.CancelledError:
            if waiter[0].done() and not waiter[0].cancelled():
                # the lock was handed to the cancelled waiter, it goes on to the next one
                self.release()
            raise
        finally:
            with contextlib.suppress(ValueError):
                self._waiters.remove(waiter)
        return True

    def release(self) -> None:
        if not self._locked:
            raise RuntimeError("Lock is not acquired")
        self._locked = False
        if any(not waiter[0].done() for waiter in self._waiters):
            # the next owner is chosen in the next step of the loop: the task which released the lock queues
            # its next request first, the consecutive requests of a change are not interleaved by the scans
            asyncio.get_running_loop().call_soon(self._wake)

    def _wake(self) -> None:
        """Hand the lock to the waiter of the high priority, else to the first one"""
        waiting = [waiter for waiter in self._waiters if not waiter[0].done()]
        if self._locked or not waiting:
            return
        waiter = next((waiter for waiter in waiting if self._high(waiter[1])), waiting[0])
        self._waiters.remove(waiter)
        self._locked = True
        waiter[0].set_result(True)

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, *exc):
        self.release()


class BusTransport(AsyncSmartTransport):
    """The transport of a Modbus bus, shared by its units

    A unit which does not respond (its scan failed) is probed by one request with probe_timeout,
    without the retries. Every scan of a missing unit locked the bus for (retries + 1) * timeout
    and the other units of the bus waited, e.g. 1 s with the defaults.

    The probe uses the lock of the bus and the reconnection of AsyncSmartTransport (tmodbus 0.6.2),
    a cancelled request is discarded by the transport as a timed out one, its late response too.

    The lock of the bus is a PriorityLock: the requests of a unit with a waiting change (priority()) go
    before the requests of the scans of the other units, which wait in the order of their arrival.
    """

    def __init__(self, base_transport, *, probe_timeout: float, **kwargs):
        super().__init__(base_transport, **kwargs)
        self.probe_timeout = probe_timeout
        self.failing_units: set[int] = set()  # the unit ids probed by one request, set by ModbusScanner
        self._single_units: set[int] = set()  # the unit ids sent one request, see single_request()
        self._priority_units: collections.Counter[int] = collections.Counter()  # see priority()
        self._communication_lock = PriorityLock(lambda unit_id: self._priority_units[unit_id] > 0)

    def set_failing(self, unit_id: int, failing: bool):
        if failing:
            self.failing_units.add(unit_id)
        else:
            self.failing_units.discard(unit_id)

    @contextlib.contextmanager
    def single_request(self, unit_id: int):
        """The requests of the unit are sent once with probe_timeout, without the retries, e.g. a write after
        which the unit restarts and does not respond; a retry repeated the restart
        """
        self._single_units.add(unit_id)
        try:
            yield
        finally:
            self._single_units.discard(unit_id)

    @contextlib.contextmanager
    def priority(self, unit_id: int):
        """The requests of the unit go first, also the waiting ones, e.g. while a change of the unit waits for
        the scan of the unit, then writes and reads the unit
        """
        self._priority_units[unit_id] += 1
        try:
            yield
        finally:
            self._priority_units[unit_id] -= 1
            if not self._priority_units[unit_id]:
                del self._priority_units[unit_id]

    async def send_and_receive(self, unit_id, pdu):
        _REQUEST_UNIT.set(unit_id)
        if unit_id not in self.failing_units and unit_id not in self._single_units:
            return await super().send_and_receive(unit_id, pdu)
        async with self._communication_lock:
            try:
                return await asyncio.wait_for(self._reconnect_send_and_receive(unit_id, pdu), self.probe_timeout)
            except TimeoutError as E:
                # wait_for has no text, the transport says the timeout
                raise TimeoutError(f"No response to the probe after {self.probe_timeout} seconds") from E
            finally:
                self._last_request_finished_at = time.monotonic()
