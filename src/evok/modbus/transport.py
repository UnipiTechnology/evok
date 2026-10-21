import asyncio
import collections
import contextlib
import contextvars
import time

from tmodbus import AsyncSmartTransport

# the unit id of the request of the running task, the key of its waiter in the lock of the bus
_REQUEST_UNIT: contextvars.ContextVar[int | None] = contextvars.ContextVar("request_unit", default=None)
# the unit id of the session (a change) of the running task, see BusTransport.session()
_SESSION_UNIT: contextvars.ContextVar[int | None] = contextvars.ContextVar("session_unit", default=None)


class SessionLock:
    """The asyncio lock of a bus with the sessions of its units, e.g. the changes

    A request of a session of its unit goes before the other requests. The other requests of a unit with
    a session wait until it ends, e.g. its scan does not read the unit between the writes of a change;
    the other requests of the other units wait in the order of their arrival and use the bus while
    a session has no request. After each session the first waiting other request of its unit and the first
    one of another unit go first, a stream of the changes does not stop the scans.

    The key of a waiter is the unit id of its request (_REQUEST_UNIT) and whether it runs in the session
    of the unit (_SESSION_UNIT), tmodbus uses the lock by async with.
    """

    def __init__(self):
        self._locked = False
        self._waiters: collections.deque[tuple[asyncio.Future, int | None, bool]] = collections.deque()
        self._sessions: collections.Counter[int] = collections.Counter()  # the running and waiting ones
        self._turns: set[int] = set()  # the units whose other request goes first after their session
        self._other_turn = False  # an other request of another unit goes first after a session

    def locked(self) -> bool:
        return self._locked

    @contextlib.contextmanager
    def session(self, unit_id: int):
        self._sessions[unit_id] += 1
        token = _SESSION_UNIT.set(unit_id)
        try:
            yield
        finally:
            _SESSION_UNIT.reset(token)
            self._sessions[unit_id] -= 1
            if not self._sessions[unit_id]:
                del self._sessions[unit_id]
            others = [unit for _, unit, in_session in self._pending() if not in_session]
            if unit_id in others:
                self._turns.add(unit_id)
            if any(unit != unit_id for unit in others):
                self._other_turn = True
            self._schedule_wake()

    def _pending(self):
        return [waiter for waiter in self._waiters if not waiter[0].done()]

    def _blocked(self, unit_id: int | None, in_session: bool) -> bool:
        return not in_session and unit_id in self._sessions and unit_id not in self._turns

    async def acquire(self) -> bool:
        unit_id = _REQUEST_UNIT.get()
        # a task created in a session inherits its context, e.g. a pulse, after the session it is not in it
        in_session = unit_id is not None and _SESSION_UNIT.get() == unit_id and unit_id in self._sessions
        if not self._locked and not self._pending() and not self._blocked(unit_id, in_session):
            self._locked = True
            return True
        waiter = (asyncio.get_running_loop().create_future(), unit_id, in_session)
        self._waiters.append(waiter)
        try:
            if not self._locked:
                self._wake()
            await waiter[0]
        except asyncio.CancelledError:
            if waiter[0].done() and not waiter[0].cancelled():
                # the lock was handed to the cancelled waiter, it goes on to the next one
                self.release()
            raise
        finally:
            with contextlib.suppress(ValueError):
                self._waiters.remove(waiter)
            self._prune_turns()
        return True

    def _prune_turns(self) -> None:
        """Drop the turns of the cancelled requests, a turn left without its request would let the next scan
        of the unit into its session
        """
        others = {unit for _, unit, in_session in self._pending() if not in_session}
        self._turns &= others
        if not others:
            self._other_turn = False

    def release(self) -> None:
        if not self._locked:
            raise RuntimeError("Lock is not acquired")
        self._locked = False
        # the next owner is chosen in the next step of the loop: the task which released the lock queues
        # its next request first, the consecutive requests of a change are not interleaved by the scans
        self._schedule_wake()

    def _schedule_wake(self) -> None:
        if self._pending():
            asyncio.get_running_loop().call_soon(self._wake)

    def _wake(self) -> None:
        """Hand the lock to the other requests after a session, else to a request of a session, else
        to the first other request which is not blocked by the session of its unit
        """
        waiting = self._pending()
        if self._locked or not waiting:
            return
        waiter = (
            next((w for w in waiting if not w[2] and w[1] in self._turns), None)
            or (self._other_turn and next((w for w in waiting if not self._blocked(w[1], w[2])), None))
            or next((w for w in waiting if w[2]), None)
            or next((w for w in waiting if not self._blocked(w[1], w[2])), None)
        )
        if not waiter:
            return
        if not waiter[2]:
            if waiter[1] in self._turns:
                self._turns.discard(waiter[1])
            else:
                self._other_turn = False
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

    The lock of the bus is a SessionLock: the requests of a change of a unit (session()) go before the scans,
    the scan of the unit waits until the change ends.
    """

    def __init__(self, base_transport, *, probe_timeout: float, **kwargs):
        super().__init__(base_transport, **kwargs)
        self.probe_timeout = probe_timeout
        self.failing_units: set[int] = set()  # the unit ids probed by one request, set by ModbusScanner
        self._single_units: set[int] = set()  # the unit ids sent one request, see single_request()
        self._communication_lock = SessionLock()

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

    def session(self, unit_id: int):
        """The requests of the running task to the unit go first, the other requests of the unit, its scan,
        wait until the session ends, e.g. a change of the unit: its writes and the read after them
        """
        return self._communication_lock.session(unit_id)

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
