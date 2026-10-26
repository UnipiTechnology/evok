"""Sequences of changes of a device timed by Evok, e.g. the pulse of an output

A sequence is a list of steps, each one sets the params of set() of the device after its delay.
At most one sequence runs for a device: a new one replaces it, a change of the device by the API
is refused while it runs (set_devices()). finish_all() writes the final state of the running sequences
on shutdown, an output is not left in the state of a pulse; a sequence without a final state leaves
the device in its state.

A step of a device of a Modbus unit is a change of the unit (Client.change): its state and event follow
the write, it is written also on an unavailable unit. The sequence stays running until its step writes
under the lock of the unit, a change which got the lock before it cancels it; the step overwrote
the newer value of the change.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from tmodbus.exceptions import (
    AcknowledgeError,
    GatewayPathUnavailableError,
    GatewayTargetDeviceFailedToRespondError,
    InvalidRequestError,
    ModbusResponseError,
    ServerDeviceBusyError,
    TModbusError,
)

from ..devices import devents, to_bool, to_float
from ..errors import UnitCommunicationError, describe_error, root_cause

logger = logging.getLogger(__name__)

STEP_RETRY_DELAY = 1.0  # s, a failed step is written again after it, the output does not stay in its state
STEP_RETRY_MAX_DELAY = 30.0  # s, the delay doubles up to it, a missing unit does not load its bus
STEP_FAILURE_LOG = 300.0  # s, a step still failing is logged again after it, also a changed error at once
# the errors of the communication, they pass; another error of a step ends its sequence and writes its final
# state, e.g. a value refused by the device, it would be written again forever and the output refused the changes
STEP_RETRIED = (UnitCommunicationError, TModbusError, TimeoutError, OSError)
# the request refused by the unit (an exception response, e.g. Illegal Data Value or Server Device Failure)
# or invalid, it would be refused again
STEP_REFUSED = (ModbusResponseError, InvalidRequestError)
# the exception responses which pass, e.g. a busy unit or a gateway without its target
STEP_TRANSIENT = (
    ServerDeviceBusyError,
    AcknowledgeError,
    GatewayPathUnavailableError,
    GatewayTargetDeviceFailedToRespondError,
)


def _retried(error: Exception) -> bool:
    """An error of the communication, not a request refused by the unit"""
    cause = root_cause(error)
    return isinstance(error, STEP_RETRIED) and (
        not isinstance(cause, STEP_REFUSED) or isinstance(cause, STEP_TRANSIENT)
    )


@dataclass
class Step:
    params: dict  # the params of set() of the device
    delay: float = 0.0  # s, the wait before the step


@dataclass
class Sequence:
    steps: list[Step]
    final: dict | None = None  # the params of set() written when the sequence is finished early, e.g. on shutdown
    name: str = "sequence"


def pulse(value: int, duration: float) -> Sequence:
    """The rest of a pulse after its value has been set: the opposite value after the duration"""
    end = {"value": 1 - value}
    return Sequence([Step(end, duration)], final=end, name="pulse")


def _name(device) -> str:
    return f"{str(getattr(device, 'devtype', 'device')).upper()} {getattr(device, 'circuit', '')}"


def pulse_params(device, kw: dict) -> tuple[dict, Sequence | None]:
    """Split pulse_duration from the params, the pulse of the value of the output.
    Raise ValueError if they are invalid, before any write.
    """
    kw = dict(kw)
    duration = kw.pop("pulse_duration", None)
    if duration is None:
        return kw, None
    if kw.get("value") is None:
        raise ValueError(f"{_name(device)}: pulse_duration requires value")
    duration = to_float(duration)
    if duration <= 0:
        raise ValueError(f"{_name(device)}: pulse_duration {duration} must be positive")
    # the pulse inverts the parsed value, e.g. the string '0'
    return kw, pulse(int(to_bool(kw["value"])), duration)


@dataclass
class Running:
    task: asyncio.Task
    sequence: Sequence
    step: int = 0  # the number of the done steps
    finished: bool = False  # the last step was written, the sequence ended by it


class Sequencer:
    """The running sequences of the devices, the listeners are called when a sequence starts, does a step
    and ends
    """

    def __init__(self):
        self._running: dict[object, Running] = {}
        self._writing: set[asyncio.Task] = set()  # the tasks writing a step, they are not cancelled
        self._listeners: list = []

    def subscribe(self, listener):
        """listener(device) is called when a sequence of the device starts, does a step or ends"""
        self._listeners.append(listener)

    def _notify(self, device):
        for listener in self._listeners:
            try:
                listener(device)
            except Exception:
                logger.exception(f"{_name(device)}: listener of the sequencer failed")

    def is_running(self, device) -> bool:
        return device in self._running

    def running(self, device) -> Running | None:
        """The running sequence of the device and its progress"""
        return self._running.get(device)

    def sequence(self, device) -> Sequence | None:
        """The running sequence of the device"""
        entry = self._running.get(device)
        return None if entry is None else entry.sequence

    def _stop(self, entry: Running):
        """Stop the task of the sequence; a task writing its step is not cancelled, the write would be
        interrupted in the middle of a Modbus request, it ends after the write
        """
        if entry.task not in self._writing:
            entry.task.cancel()

    def start(self, device, sequence: Sequence):
        """Run the sequence of the device, it replaces the running one"""
        entry = self._running.pop(device, None)
        if entry is not None:
            self._stop(entry)
        self._running[device] = Running(asyncio.create_task(self._run(device, sequence)), sequence)
        self._notify(device)

    def cancel(self, device):
        """Stop the sequence of the device without its final state"""
        entry = self._running.pop(device, None)
        if entry is not None:
            self._stop(entry)
            self._notify(device)

    def cancel_all(self):
        for device in list(self._running):
            self.cancel(device)

    def _current(self, device, task: asyncio.Task) -> bool:
        entry = self._running.get(device)
        return entry is not None and entry.task is task

    def _end(self, device, task: asyncio.Task) -> bool:
        """Remove the sequence of the task if it is still the running one"""
        if not self._current(device, task):
            return False
        del self._running[device]
        self._notify(device)
        return True

    async def _run(self, device, sequence: Sequence):
        task = asyncio.current_task()
        step_number = 0
        try:
            for step_number, step in enumerate(sequence.steps, 1):
                await asyncio.sleep(step.delay)
                last = step_number == len(sequence.steps)
                if not await self._apply_step(device, sequence, step, task, step_number, last):
                    return
                if not last:
                    if not self._current(device, task):
                        # cancelled or replaced while it wrote the step
                        return
                    self._notify(device)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"{_name(device)}: step {step_number} of the {sequence.name} failed, it is ended")
            if sequence.final is not None and self._current(device, task):
                # the output does not stay in the state of the sequence: the final state is written as its last
                # step, the sequence runs until it is written (a change of the output meanwhile is refused,
                # finish_all() waits for it), an error of the communication is written again
                try:
                    await self._apply_step(
                        device, sequence, Step(sequence.final), task, step_number - 1, True, what="final state"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(f"{_name(device)}: final state of the {sequence.name} failed")
        finally:
            self._end(device, task)

    async def _apply_step(
        self, device, sequence: Sequence, step: Step, task, step_number: int, last: bool, what: str | None = None
    ) -> bool:
        """Write the step until it succeeds, the sequence stays running meanwhile, e.g. a noise on the bus at
        the end of a pulse; False if the sequence was cancelled or replaced meanwhile
        """
        what = what or f"step {step_number}"
        failures, delay = 0, STEP_RETRY_DELAY
        logged, logged_at = None, 0.0
        while True:
            try:
                applied = await self._apply(device, step.params, task, step_number, last)
            except Exception as E:
                if not _retried(E):
                    raise
                if not self._current(device, task):
                    return False
                failures += 1
                # the kind of the error, its text may differ by each attempt
                now, kind = time.monotonic(), type(root_cause(E))
                if logged is None:
                    logger.exception(
                        f"{_name(device)}: {what} of the {sequence.name} failed, it is written again "
                        f"after {STEP_RETRY_DELAY}..{STEP_RETRY_MAX_DELAY} s"
                    )
                    logged, logged_at = kind, now
                elif kind != logged or now - logged_at >= STEP_FAILURE_LOG:
                    # a changed error, or a reminder that the output is still in the state of the sequence
                    logger.error(
                        f"{_name(device)}: {what} of the {sequence.name} failed {failures}x: {describe_error(E)}"
                    )
                    logged, logged_at = kind, now
                await asyncio.sleep(delay)
                delay = min(delay * 2, STEP_RETRY_MAX_DELAY)
                continue
            if failures and applied:
                logger.info(f"{_name(device)}: {what} of the {sequence.name} written after {failures} failures")
            return applied

    async def _apply(self, device, params: dict, task: asyncio.Task | None = None, step_number=0, last=False) -> bool:
        """Set the params of a step, False if the sequence was cancelled or replaced meanwhile"""
        applied = False

        async def operation():
            nonlocal applied
            if task is not None:
                entry = self._running.get(device)
                if entry is None or entry.task is not task:
                    return
                self._writing.add(task)
            try:
                await device.set(**params)
            finally:
                self._writing.discard(task)
            if task is not None:
                # done after the successful write, a failed step is written again and it is not reported as done
                entry.step = step_number
                if last:
                    # the state read after the write is not running; finish_all() does not write the final state
                    entry.finished = True
                    self._end(device, task)
            applied = True

        change = getattr(getattr(device, "client", None), "change", None)
        if change is not None:
            # also on an unavailable unit, the output must not stay in the state of the sequence
            await change(operation, check_available=False, devices=[device])
        else:
            await operation()
            devents.status(device)
        return applied

    async def finish_all(self, timeout: float = 5.0):
        """Stop the running sequences and write their final states, used on shutdown; the steps being
        written are finished first. A sequence without a final state leaves the device in its state.
        """
        entries = list(self._running.items())
        self._running.clear()
        for device, entry in entries:
            self._stop(entry)
            self._notify(device)
        candidates = [(device, entry) for device, entry in entries if entry.sequence.final is not None]
        writing = list(self._writing)
        if not candidates and not writing:
            return
        logger.info(f"Finishing {len(candidates)} running sequences")

        async def finish():
            if writing:
                await asyncio.wait(writing)
            # a sequence whose last step was written ended by it; a failed write of the last step is written
            # by the final state
            finals = [(device, entry.sequence) for device, entry in candidates if not entry.finished]
            await asyncio.gather(*(self._finish(device, sequence) for device, sequence in finals))

        try:
            await asyncio.wait_for(finish(), timeout)
        except TimeoutError:
            logger.error("Finishing of the running sequences timed out, some outputs may stay in their state")

    async def _finish(self, device, sequence: Sequence):
        try:
            await self._apply(device, sequence.final)
        except Exception:
            logger.exception(f"{_name(device)}: final state of the {sequence.name} failed")


# the sequences of all devices
sequencer = Sequencer()
