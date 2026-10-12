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

from ..devices import DO, devents, to_bool, to_float
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
    """ Split pulse_duration from the params of set() of an output, the pulse of the value; timeout of a DO is
        its deprecated alias. Raise ValueError if they are invalid, before any write.
    """
    kw = dict(kw)
    duration = kw.pop('pulse_duration', None)
    if getattr(device, 'devtype', None) == DO and 'timeout' in kw:
        timeout = kw.pop('timeout')
        if timeout is not None:
            if duration is not None:
                raise ValueError(f'{_name(device)}: timeout is a deprecated alias of pulse_duration, do not set both')
            duration = timeout
    if duration is None:
        return kw, None
    if kw.get('value') is None:
        raise ValueError(f'{_name(device)}: pulse_duration requires value')
    duration = to_float(duration)
    if duration <= 0:
        raise ValueError(f'{_name(device)}: pulse_duration {duration} must be positive')
    # the pulse inverts the parsed value, e.g. the string '0'
    return kw, pulse(int(to_bool(kw['value'])), duration)


class Sequencer:
    """ The running sequences of the devices """

    def __init__(self):
        self._running: dict[object, tuple[asyncio.Task, Sequence]] = {}

    def is_running(self, device) -> bool:
        return device in self._running

    def sequence(self, device) -> Sequence | None:
        """ The running sequence of the device """
        entry = self._running.get(device)
        return None if entry is None else entry[1]

    def start(self, device, sequence: Sequence):
        """ Run the sequence of the device, it replaces the running one """
        self.cancel(device)
        task = asyncio.create_task(self._run(device, sequence))
        self._running[device] = (task, sequence)

    def cancel(self, device):
        """ Stop the sequence of the device without its final state, e.g. a change by the API """
        entry = self._running.pop(device, None)
        if entry is not None:
            entry[0].cancel()

    def cancel_all(self):
        for device in list(self._running):
            self.cancel(device)

    async def _run(self, device, sequence: Sequence):
        task = asyncio.current_task()
        step_number = 0
        try:
            for step_number, step in enumerate(sequence.steps, 1):
                await asyncio.sleep(step.delay)
                if not await self._apply(device, step.params, task, last=step_number == len(sequence.steps)):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(f"{_name(device)}: step {step_number} of the {sequence.name} failed")
        finally:
            entry = self._running.get(device)
            if entry is not None and entry[0] is task:
                del self._running[device]

    async def _apply(self, device, params: dict, task: asyncio.Task | None = None, last=False) -> bool:
        """ Set the params of a step, False if the sequence was cancelled or replaced meanwhile """
        applied = False

        async def operation():
            nonlocal applied
            if task is not None:
                entry = self._running.get(device)
                if entry is None or entry[0] is not task:
                    return
                if last:
                    # the state read after the write is not pending
                    del self._running[device]
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
        for task, _ in (entry for _, entry in entries):
            task.cancel()
        finals = [(device, sequence) for device, (_, sequence) in entries if sequence.final is not None]
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
