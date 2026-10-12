""" Sequences of changes of a device timed by Evok, e.g. the pulse of an output

    A sequence is a list of steps, each one sets the params of set() of the device after its delay.
    At most one sequence runs for a device: a new one replaces it, a change of the device by the API
    cancels it (set_devices()). finish_all() writes the final state of the running sequences on shutdown,
    an output is not left in the state of a pulse.

    A step of a device of a Modbus unit is a change of the unit (Client.change): its state and event follow
    the write, it is written also on an unavailable unit. The sequence stays running until its step writes
    under the lock of the unit, a change which got the lock before it cancels it; the step overwrote
    the newer value of the change.
"""
import asyncio
from dataclasses import dataclass

from ..devices import devents, to_bool, to_float
from ..log import logger


@dataclass
class Step:
    params: dict            # the params of set() of the device
    delay: float = 0.0      # s, the wait before the step


@dataclass
class Sequence:
    steps: list[Step]
    final: dict | None = None   # the params of set() written when the sequence is finished early, e.g. on shutdown
    name: str = 'sequence'


def pulse(value: int, duration: float) -> Sequence:
    """ The rest of a pulse after its value has been set: the opposite value after the duration """
    end = {'value': 1 - value}
    return Sequence([Step(end, duration)], final=end, name='pulse')


def _name(device) -> str:
    return f"{str(getattr(device, 'devtype', 'device')).upper()} {getattr(device, 'circuit', '')}"


def pulse_params(device, kw: dict) -> tuple[dict, Sequence | None]:
    """ Split pulse_duration from the params, the pulse of the value of the output.
        Raise ValueError if they are invalid, before any write.
    """
    kw = dict(kw)
    duration = kw.pop('pulse_duration', None)
    if duration is None:
        return kw, None
    if kw.get('value') is None:
        raise ValueError(f'{_name(device)}: pulse_duration requires value')
    duration = to_float(duration)
    if duration <= 0:
        raise ValueError(f'{_name(device)}: pulse_duration {duration} must be positive')
    # the pulse inverts the parsed value, e.g. the string '0'
    return kw, pulse(int(to_bool(kw['value'])), duration)


@dataclass
class Running:
    task: asyncio.Task
    sequence: Sequence
    step: int = 0       # the number of the done steps


class Sequencer:
    """ The running sequences of the devices, the listeners are called when a sequence starts or ends """

    def __init__(self):
        self._running: dict[object, Running] = {}
        self._listeners: list = []

    def subscribe(self, listener):
        """ listener(device) is called when a sequence of the device starts or ends """
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
        """ The running sequence of the device and its progress """
        return self._running.get(device)

    def sequence(self, device) -> Sequence | None:
        """ The running sequence of the device """
        entry = self._running.get(device)
        return None if entry is None else entry.sequence

    def start(self, device, sequence: Sequence):
        """ Run the sequence of the device, it replaces the running one """
        entry = self._running.pop(device, None)
        if entry is not None:
            entry.task.cancel()
        self._running[device] = Running(asyncio.create_task(self._run(device, sequence)), sequence)
        self._notify(device)

    def cancel(self, device):
        """ Stop the sequence of the device without its final state, e.g. a change by the API """
        entry = self._running.pop(device, None)
        if entry is not None:
            entry.task.cancel()
            self._notify(device)

    def cancel_all(self):
        for device in list(self._running):
            self.cancel(device)

    def _end(self, device, task: asyncio.Task) -> bool:
        """ Remove the sequence of the task if it is still the running one """
        entry = self._running.get(device)
        if entry is None or entry.task is not task:
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
                if not await self._apply(device, step.params, task, step_number, last):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"{_name(device)}: step {step_number} of the {sequence.name} failed")
        finally:
            self._end(device, task)

    async def _apply(self, device, params: dict, task: asyncio.Task | None = None, step_number=0, last=False) -> bool:
        """ Set the params of a step, False if the sequence was cancelled or replaced meanwhile """
        applied = False

        async def operation():
            nonlocal applied
            if task is not None:
                entry = self._running.get(device)
                if entry is None or entry.task is not task:
                    return
                entry.step = step_number
                if last:
                    # the state read after the write is not running
                    self._end(device, task)
            await device.set(**params)
            applied = True

        change = getattr(getattr(device, 'client', None), 'change', None)
        if change is not None:
            # also on an unavailable unit, the output must not stay in the state of the sequence
            await change(operation, check_available=False)
        else:
            await operation()
            devents.status(device)
        return applied

    async def finish_all(self, timeout: float = 5.0):
        """ Stop the running sequences and write their final states, used on shutdown """
        entries = list(self._running.items())
        self._running.clear()
        for device, entry in entries:
            entry.task.cancel()
            self._notify(device)
        finals = [(device, entry.sequence) for device, entry in entries if entry.sequence.final is not None]
        if not finals:
            return
        logger.info(f"Finishing {len(finals)} running sequences")
        try:
            await asyncio.wait_for(asyncio.gather(*(self._finish(device, sequence) for device, sequence in finals)),
                                   timeout)
        except TimeoutError:
            logger.error("Finishing of the running sequences timed out, some outputs may stay in their state")

    async def _finish(self, device, sequence: Sequence):
        try:
            await self._apply(device, sequence.final)
        except Exception:
            logger.exception(f"{_name(device)}: final state of the {sequence.name} failed")


# the sequences of all devices
sequencer = Sequencer()
