#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:34:57 2026

@author: bokula
"""
import asyncio

from typing import Union

from ..devices import DI, DO, RO, LED, Devices
from ..log import logger
from .base import IODevice
from .client import Client, Accessor, AccessorBit, AccessorU16, AccessorU32
from .iomode import DIMode, WithDIMode
from .pwm import PwmFrequency


class DigitalOutput(IODevice):

    devtype = DO
    pending_task: Union[None, asyncio.Task] = None

    def __init__(self, circuit, client: Client, coil, reg, mask, major_group=0,
                 pwm: Union[None, PwmFrequency] = None, pwmdutyreg=-1, modes=None):
        """ pwm is the frequency shared by the outputs of the group, pwmdutyreg the duty register of this output """
        super().__init__(circuit, client, major_group)
        self.modes = modes if modes is not None else ['Simple']
        self.pwm = pwm
        self.pwmdutyreg = pwmdutyreg
        self.accessor_pwm_duty = AccessorU16(pwmdutyreg) if pwm is not None else Accessor(None)
        self.pwm_duty = None
        self.pwm_duty_val = None
        self.pwm_freq = None
        self.mode = None
        self.coil = coil
        self.accessor = AccessorBit(reg, mask)
        self.value = None

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
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
        if forced_value is not None:
            ret['value'] = forced_value
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

    async def set(self, value=None, timeout=None, mode=None, pwm_freq=None, pwm_duty=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts """
        try:
            if self.pending_task is not None:
                self.pending_task.cancel()
                self.pending_task = None

            if pwm_duty is not None:
                pwm_duty = float(pwm_duty)

            if pwm_freq is not None:
                pwm_freq = float(pwm_freq)

            # if pwm_duty is not None and self.mode == 'PWM' and float(pwm_duty) <= 0.01:
            #    mode = 'Simple'
            # New system - mode field will no longer be used

            if (pwm_freq is not None) and (pwm_freq > 0):
                await self.set_pwm_freq(pwm_freq)

            # Set Binary value
            if value is not None:

                parsed_value = 1 if int(value) else 0

                if pwm_duty is not None:
                    # No conflict in this case
                    if (pwm_duty == 100 and parsed_value == 1) or (pwm_duty == 0 and parsed_value == 0):
                        pass
                    else:
                        raise ValueError('Set value conflict: Cannot set both value and pwm_duty at once.')

                if timeout is not None:
                    timeout = float(timeout)

                self.mode = 'Simple'
                await self.client.mb_client.write_single_coil(self.coil, parsed_value)
                if self.pwm_duty:
                    self.pwm_duty = 0
                    # Turn off PWM
                    await self.accessor_pwm_duty.write(self.client, 0)

            # Set PWM Duty
            elif pwm_duty is not None and 0.0 <= pwm_duty <= 100.0:
                if self.value != 0:
                    await self.client.mb_client.write_single_coil(self.coil, 0)
                await self.accessor_pwm_duty.write(self.client, self.pwm.duty_raw(pwm_duty))
                self.mode = 'PWM'

            self.set_alias(alias)

            if timeout is None:
                return

            async def timercallback():
                await asyncio.sleep(float(timeout))
                self.pending_task = None
                await self.client.mb_client.write_single_coil(self.coil, 0 if value else 1)

            self.pending_task = asyncio.create_task(timercallback())

        except Exception as E:
            logger.error(f"Error in set DO: {E}")
            raise E

    async def set_pwm_freq(self, freq: float):
        """ Set the frequency shared by the group, keep the duty cycle of all its outputs """
        await self.pwm.set(freq)
        for dev in Devices.by_name(DO, major_group=self.major_group):
            if dev.pwm is not self.pwm:
                continue
            dev.pwm_freq = self.pwm.freq
            if dev.pwm_duty:
                raw = self.pwm.duty_raw(dev.pwm_duty)
                if raw != dev.pwm_duty_val:
                    await dev.accessor_pwm_duty.write(self.client, raw)
                    dev.pwm_duty_val = raw


class Relay(IODevice):

    devtype = RO

    def __init__(self, circuit, client: Client, coil, reg, mask, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.accessor = AccessorBit(reg, mask)
        self.value = None

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
        ret = {'dev': 'ro',
               'circuit': self.circuit,
               'value': self.value,
               }
        self._with_alias(ret)
        if forced_value is not None:
            ret['value'] = forced_value
        return ret

    async def check_new_data(self):
        old_value = self.value
        self.value = self.accessor.read(self.client)
        return old_value != self.value

    async def set(self, value=None, alias=None):
        """ Sets new on/off status """
        if value is not None:
            parsed_value = 1 if int(value) else 0
            await self.client.mb_client.write_single_coil(self.coil, parsed_value)

        self.set_alias(alias)


class ULED(Relay):

    devtype = LED

    def full(self):
        ret = {'dev': 'led', 'circuit': self.circuit, 'value': self.value}
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
        self.regcounter = regcounter
        self.accessor_counter = AccessorU32(regcounter) if regcounter is not None else Accessor(None)
        self.regdebounce = regdebounce
        self.accessor_debounce = AccessorU16(regdebounce) if regdebounce is not None else Accessor(None)
        self.value = None
        self.counter = None
        self.debounce = None

    async def check_new_data(self):
        mode_changed = self.dimode.update()

        old_value = self.value
        old_counter = self.counter
        self.value = self.accessor.read(self.client)
        self.counter = self.read_counter()
        self.debounce = self.accessor_debounce.read(self.client)
        return mode_changed or old_counter != self.counter or old_value != self.value

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
        self.set_alias(alias)

        await self.dimode.set(mode, ds_mode)

        if counter_mode is not None and counter_mode in self.counter_modes and counter_mode != self.counter_mode:
            self.counter_mode = counter_mode
            self.counter = self.read_counter()

        if debounce is not None:
            if self.regdebounce is not None:
                await self.accessor_debounce.write(self.client, int(float(debounce)))
        if counter is not None:
            if self.regcounter is not None:
                await self.accessor_counter.write(self.client, int(float(counter)))
