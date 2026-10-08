#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio

from ..devices import DI, DO, RO, LED, Devices, to_bool, to_float
from ..log import logger
from .base import IODevice
from .client import Client, Accessor, AccessorBit, AccessorU16, AccessorU32
from .iomode import DIMode, WithDIMode
from .pwm import PwmFrequency


class WithPulse:
    """ Mixin for the outputs with a coil, which set a value for a single pulse

        After pulse_duration seconds the opposite of the value is written,
        the output is pending until then. The pulse is timed by Evok,
        finish_pulses() ends the pending pulses on shutdown.
    """

    devtype: str
    circuit: str
    client: Client
    coil: int
    pending_task: asyncio.Task | None = None
    pulse_end_value: int | None = None

    def _check_pulse(self, parsed_value, pulse_duration) -> float | None:
        """ Return pulse_duration as a float, raise ValueError if it is invalid """
        if pulse_duration is None:
            return None
        if parsed_value is None:
            raise ValueError(f'{self.devtype.upper()} {self.circuit}: pulse_duration requires value')
        pulse_duration = to_float(pulse_duration)
        if pulse_duration <= 0:
            raise ValueError(f'{self.devtype.upper()} {self.circuit}: pulse_duration {pulse_duration} must be positive')
        return pulse_duration

    def _cancel_pulse(self):
        if self.pending_task is not None:
            self.pending_task.cancel()
            self.pending_task = None

    def _start_pulse(self, parsed_value, pulse_duration):
        """ Call after the value has been written """
        async def timercallback():
            await asyncio.sleep(pulse_duration)
            self.pending_task = None
            await self._end_pulse(end_value)

        # a concurrent set() could start a pulse while this one awaited the writes
        self._cancel_pulse()
        end_value = self.pulse_end_value = 1 - parsed_value
        self.pending_task = asyncio.create_task(timercallback())

    async def _end_pulse(self, end_value):
        try:
            await self.client.mb_client.write_single_coil(self.coil, end_value)
        except Exception:
            logger.exception(f"{self.devtype.upper()} {self.circuit}: end of the pulse failed")

    async def finish_pulse(self):
        """ End the pending pulse now, the output is not left in the state of the pulse """
        if self.pending_task is None:
            return
        self._cancel_pulse()
        await self._end_pulse(self.pulse_end_value)


async def finish_pulses(timeout: float = 5.0):
    """ End the pending pulses of all outputs, used on shutdown """
    outputs = [dev for devtype in (DO, RO, LED) for dev in Devices.by_name(devtype)
               if isinstance(dev, WithPulse) and dev.pending_task is not None]
    if not outputs:
        return
    logger.info(f"Ending {len(outputs)} pending pulses")
    try:
        await asyncio.wait_for(asyncio.gather(*(dev.finish_pulse() for dev in outputs)), timeout)
    except TimeoutError:
        logger.error("Ending of the pending pulses timed out, some outputs may stay in the state of the pulse")


class DigitalOutput(WithPulse, IODevice):

    devtype = DO

    def __init__(self, circuit, client: Client, coil, reg, mask, major_group=0,
                 pwm: PwmFrequency | None = None, pwmdutyreg=None, modes=None):
        """ pwm is the frequency shared by the outputs of the group, pwmdutyreg the duty register of this output """
        super().__init__(circuit, client, major_group)
        if pwm is not None and pwmdutyreg is None:
            raise ValueError(f'DO {circuit}: pwm requires pwmdutyreg')
        self.modes = modes if modes is not None else ['Simple']
        self.pwm = pwm
        self.accessor_pwm_duty = AccessorU16(pwmdutyreg) if pwm is not None else Accessor(None)
        self.pwm_duty = None
        self.pwm_duty_val = None
        self.pwm_freq = None
        self.mode = None
        self.coil = coil
        self.accessor = AccessorBit(reg, mask)
        self.value = None

    def full(self):
        ret = {'dev': 'do',
               'circuit': self.circuit,
               'value': self.value,
               'pending': self.pending_task is not None,
               'mode': self.mode,
               'modes': self.modes,
               'pwm_freq': self.pwm_freq,
               'pwm_duty': self.pwm_duty,
               }
        self._with_alias(ret)
        return ret

    async def check_new_data(self):
        is_change = False
        if self.pwm is not None:
            self.pwm.update()
            old_pwm = (self.pwm_freq, self.pwm_duty)
            self.pwm_freq = self.pwm.freq
            self.pwm_duty_val = self.accessor_pwm_duty.read(self.client)
            self.pwm_duty = self.pwm.duty(self.pwm_duty_val)
            is_change = old_pwm != (self.pwm_freq, self.pwm_duty)
        # Mode field is for backward compatibility, will be deprecated soon
        self.mode = 'PWM' if self.pwm_duty else 'Simple'

        old_value = self.value
        self.value = self.accessor.read(self.client)
        return is_change or old_value != self.value

    async def set(self, value=None, pulse_duration=None, mode=None, pwm_freq=None, pwm_duty=None, alias=None,
                  timeout=None):
        """ Sets new on/off status. A new value or pwm_duty disables the pending pulse

            pulse_duration in seconds sets the opposite of value after the pulse, it requires value,
            timeout is its deprecated alias
        """
        if timeout is not None:
            if pulse_duration is not None:
                raise ValueError(f'DO {self.circuit}: timeout is a deprecated alias of pulse_duration, '
                                 f'do not set both')
            pulse_duration = timeout

        # parse before any write, the pulse inverts the parsed value
        parsed_value = None if value is None else int(to_bool(value))
        pulse_duration = self._check_pulse(parsed_value, pulse_duration)

        if pwm_duty is not None:
            pwm_duty = to_float(pwm_duty)
            if not 0.0 <= pwm_duty <= 100.0:
                raise ValueError(f'DO {self.circuit}: pwm_duty {pwm_duty} is out of range <0..100>')

        if pwm_freq is not None:
            pwm_freq = to_float(pwm_freq)
            if pwm_freq <= 0:
                raise ValueError(f'DO {self.circuit}: pwm_freq {pwm_freq} must be positive')

        if self.pwm is None and (pwm_duty is not None or pwm_freq is not None):
            raise ValueError(f'DO {self.circuit}: PWM is not supported')

        if parsed_value is not None and pwm_duty is not None:
            # No conflict in this case
            if not ((pwm_duty == 100 and parsed_value == 1) or (pwm_duty == 0 and parsed_value == 0)):
                raise ValueError('Set value conflict: Cannot set both value and pwm_duty at once.')

        # a rejected request keeps the pending pulse
        if parsed_value is not None or pwm_duty is not None:
            self._cancel_pulse()

        if pwm_freq is not None:
            # value or pwm_duty replaces the duty of this output
            await self.set_pwm_freq(pwm_freq, keep_duty=parsed_value is None and pwm_duty is None)

        # Set Binary value
        if parsed_value is not None:
            await self.client.mb_client.write_single_coil(self.coil, parsed_value)
            if self.pwm_duty:
                self.pwm_duty = 0
                # Turn off PWM
                await self.accessor_pwm_duty.write(self.client, 0)

        # Set PWM Duty
        elif pwm_duty is not None:
            if self.value != 0:
                await self.client.mb_client.write_single_coil(self.coil, 0)
            await self.accessor_pwm_duty.write(self.client, self.pwm.duty_raw(pwm_duty))

        self.set_alias(alias)

        if pulse_duration is not None:
            self._start_pulse(parsed_value, pulse_duration)

    async def set_pwm_freq(self, freq: float, keep_duty=True):
        """ Set the frequency shared by the group, keep the duty cycle of all its outputs,
            of this output only with keep_duty
        """
        await self.pwm.set(freq)
        for dev in Devices.by_name(DO, major_group=self.major_group):
            if dev.pwm is not self.pwm:
                continue
            dev.pwm_freq = self.pwm.freq
            if dev is self and not keep_duty:
                continue
            if dev.pwm_duty:
                raw = self.pwm.duty_raw(dev.pwm_duty)
                if raw != dev.pwm_duty_val:
                    await dev.accessor_pwm_duty.write(self.client, raw)
                    dev.pwm_duty_val = raw


class Relay(WithPulse, IODevice):

    devtype = RO

    def __init__(self, circuit, client: Client, coil, reg, mask, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.accessor = AccessorBit(reg, mask)
        self.value = None

    def full(self):
        ret = {'dev': 'ro',
               'circuit': self.circuit,
               'value': self.value,
               'pending': self.pending_task is not None,
               }
        self._with_alias(ret)
        return ret

    async def check_new_data(self):
        old_value = self.value
        self.value = self.accessor.read(self.client)
        return old_value != self.value

    async def set(self, value=None, pulse_duration=None, alias=None):
        """ Sets new on/off status. A new value disables the pending pulse

            pulse_duration in seconds sets the opposite of value after the pulse, it requires value
        """
        parsed_value = None if value is None else int(to_bool(value))
        pulse_duration = self._check_pulse(parsed_value, pulse_duration)
        if parsed_value is not None:
            self._cancel_pulse()
            await self.client.mb_client.write_single_coil(self.coil, parsed_value)

        self.set_alias(alias)

        if pulse_duration is not None:
            self._start_pulse(parsed_value, pulse_duration)


class ULED(Relay):

    devtype = LED

    def full(self):
        ret = {'dev': 'led', 'circuit': self.circuit, 'value': self.value,
               'pending': self.pending_task is not None}
        self._with_alias(ret)
        return ret


class DigitalInput(WithDIMode, IODevice):

    devtype = DI

    def __init__(self, circuit, client: Client, reg, mask, regcounter=None, regdebounce=None, regmode=None,
                 regtoggle=None, regpolarity=None,
                 major_group=0, modes=None, ds_modes=None, counter_modes=None):
        super().__init__(circuit, client, major_group)
        self.dimode = DIMode(client, mask, regmode, regpolarity, regtoggle, modes, ds_modes,
                             f"{self.devtype.upper()} {circuit}")
        self.counter_modes = counter_modes if counter_modes is not None else ['Enabled', 'Disabled']
        self.counter_mode = "Enabled"
        self.accessor = AccessorBit(reg, mask)
        self.accessor_counter = AccessorU32(regcounter) if regcounter is not None else Accessor(None)
        self.accessor_debounce = AccessorU16(regdebounce) if regdebounce is not None else Accessor(None)
        self.value = None
        self.counter = None
        self.debounce = None

    async def check_new_data(self):
        mode_changed = self.dimode.update()

        old = (self.value, self.counter, self.debounce)
        self.value = self.accessor.read(self.client)
        self.counter = self.read_counter()
        self.debounce = self.accessor_debounce.read(self.client)
        return mode_changed or old != (self.value, self.counter, self.debounce)

    def read_counter(self):
        return self.accessor_counter.read(self.client) if self.counter_mode == "Enabled" else 0

    def full(self):
        ret = {'dev': 'di',
               'circuit': self.circuit,
               'value': self.value,
               'debounce': self.debounce,
               'counter_modes': self.counter_modes,
               'counter_mode': self.counter_mode,
               'counter': self.counter,
               'mode': self.mode,
               'modes': self.modes,
               }
        if self.mode == 'DirectSwitch':
            ret['ds_mode'] = self.ds_mode
            ret['ds_modes'] = self.ds_modes
        self._with_alias(ret)
        return ret

    async def set(self, debounce=None, mode=None, counter=None, counter_mode=None, ds_mode=None, alias=None):
        """ All params are validated before the first write, a disabled counter cannot be written """
        self.dimode.check(mode, ds_mode)
        if counter_mode is not None and counter_mode not in self.counter_modes:
            raise ValueError(f'DI {self.circuit}: unknown counter_mode "{counter_mode}"')
        if debounce is not None:
            debounce = self._register_value('debounce', debounce, self.accessor_debounce)
        if counter is not None:
            if (counter_mode or self.counter_mode) != 'Enabled':
                raise ValueError(f'DI {self.circuit}: the counter is disabled')
            counter = self._register_value('counter', counter, self.accessor_counter)

        await self.dimode.set(mode, ds_mode)

        if counter_mode is not None and counter_mode != self.counter_mode:
            self.counter_mode = counter_mode
            self.counter = self.read_counter()

        if debounce is not None:
            await self.accessor_debounce.write(self.client, debounce)
        if counter is not None:
            await self.accessor_counter.write(self.client, counter)

        self.set_alias(alias)

    def _register_value(self, name, value, accessor: Accessor) -> int:
        """ An integer in the range of the register, raise ValueError if the DI has no such register """
        if accessor.index is None:
            raise ValueError(f'DI {self.circuit}: {name} is not supported')
        number = to_float(value)
        if not number.is_integer():
            raise ValueError(f'DI {self.circuit}: {name} {value} must be an integer')
        low, high = accessor.raw_range
        if not low <= number <= high:
            raise ValueError(f'DI {self.circuit}: {name} {value} is out of range <{low}..{high}>')
        return int(number)
