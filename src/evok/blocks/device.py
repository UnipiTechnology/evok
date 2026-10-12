""" The sequencer of an output as a device of the API, its circuit is <devtype>_<circuit of the output>

    POST value with pulse_duration sets the value of the output for a pulse, steps (and final) run
    a sequence of the changes of the output, cancel stops the running sequence. While it runs, a change
    of the output itself is refused. The state has the output and the progress of its running sequence,
    an event is sent when a sequence starts, does a step and ends.
"""
from ..devices import Devices, SEQUENCER, devents, to_bool, to_float
from .sequencer import Sequence, Step, pulse_params, sequencer

MAX_STEPS = 100

# the sequencer devices of the outputs, their events follow the sequencer
_devices: dict = {}


def _on_change(output):
    device = _devices.get(output)
    if device is not None:
        devents.status(device)


sequencer.subscribe(_on_change)


def attach(output) -> 'SequencerDevice':
    """ Create and register the sequencer device of the output """
    device = SequencerDevice(output)
    Devices.register_device(SEQUENCER, device)
    _devices[output] = device
    return device


async def start_pulse(output, value, pulse_duration) -> dict:
    """ Set the value of the output for pulse_duration seconds, return the state of the output;
        the pulse replaces the running sequence of the output
    """
    from ..modbus import set_devices
    kw, pulse = pulse_params(output, {'value': value, 'pulse_duration': pulse_duration})
    # the value is written under the lock of the unit, after a step being written by the cancelled sequence
    sequencer.cancel(output)
    state, = await set_devices([(output, kw)])
    sequencer.start(output, pulse)
    return state


class SequencerDevice:
    devtype = SEQUENCER

    def __init__(self, output):
        self.output = output
        self.circuit = f"{output.devtype}_{output.circuit}"
        self.alias = ''
        self.major_group = getattr(output, 'major_group', None)

    def full(self) -> dict:
        running = sequencer.running(self.output)
        ret = {'dev': SEQUENCER,
               'circuit': self.circuit,
               'output': {'dev': self.output.devtype, 'circuit': self.output.circuit},
               'running': running is not None,
               'name': running.sequence.name if running else None,
               'step': running.step if running else None,
               'steps': len(running.sequence.steps) if running else None,
               }
        if self.alias:
            ret['alias'] = self.alias
        return ret

    def get(self):
        return self.full()

    async def set(self, value=None, pulse_duration=None, steps=None, final=None, cancel=None, alias=None):
        """ value with pulse_duration: a pulse of the output; steps and an optional final state: a sequence;
            cancel: stop the running sequence without its final state. One of them at once.
        """
        is_pulse = pulse_duration is not None or value is not None
        is_steps = steps is not None
        is_cancel = cancel is not None and to_bool(cancel)
        actions = [name for name, given in (('pulse_duration', is_pulse), ('steps', is_steps),
                                            ('cancel', is_cancel)) if given]
        # the whole request is checked before any change, also of the alias
        if len(actions) > 1:
            raise ValueError(f"Sequencer {self.circuit}: set only one of {' and '.join(actions)}")
        if final is not None and not is_steps:
            raise ValueError(f"Sequencer {self.circuit}: final requires steps")
        if is_pulse and pulse_duration is None:
            raise ValueError(f"Sequencer {self.circuit}: value requires pulse_duration, "
                             f"set the value of the output itself")
        sequence = self._sequence(steps, final) if is_steps else None
        if is_pulse:
            pulse_params(self.output, {'value': value, 'pulse_duration': pulse_duration})
        if alias is not None:
            Devices.set_alias(alias, self)
        if is_pulse:
            await start_pulse(self.output, value, pulse_duration)
        elif is_steps:
            sequencer.start(self.output, sequence)
        elif is_cancel:
            sequencer.cancel(self.output)
        elif alias is not None:
            # the starts and the ends are sent by the sequencer
            devents.status(self)

    def _sequence(self, steps, final) -> Sequence:
        """ The steps {"delay": seconds, <the params of the output>}, the params are checked by the schema
            of the output before the start
        """
        from ..handlers_base import check_params
        if not isinstance(steps, list) or not 0 < len(steps) <= MAX_STEPS:
            raise ValueError(f"Sequencer {self.circuit}: steps must be a list of 1..{MAX_STEPS} steps")
        sequence = []
        for number, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                raise ValueError(f"Sequencer {self.circuit}: step {number} must be an object")
            params = dict(step)
            delay = to_float(params.pop('delay', 0))
            if delay < 0:
                raise ValueError(f"Sequencer {self.circuit}: delay {delay} of step {number} must not be negative")
            if not params or 'alias' in params:
                raise ValueError(f"Sequencer {self.circuit}: step {number} must change the output, not its alias")
            check_params(self.output.devtype, params)
            sequence.append(Step(params, delay))
        if final is not None:
            if not isinstance(final, dict) or not final or 'alias' in final:
                raise ValueError(f"Sequencer {self.circuit}: final must be the params of the output")
            check_params(self.output.devtype, final)
        return Sequence(sequence, final=final, name='sequence')
