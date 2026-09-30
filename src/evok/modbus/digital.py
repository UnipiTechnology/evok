#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:34:57 2026

@author: bokula
"""
import asyncio

from copy import copy
from math import sqrt
from typing import Union

from ..devices import DI, DO, RO, OWPOWER, LED, WATCHDOG, \
                     NV_SAVE, Devices
from ..log import logger



class DigitalOutput:
    
    pending_task: Union[None, asyncio.Task] = None
    
    def __init__(self, circuit, arm, coil, reg, mask, major_group=0,
                 pwmcyclereg=-1, pwmprescalereg=-1, pwmdutyreg=-1, pwmpresetreg=-1, pwmcustompresc=-1 ,
                 legacy_mode=True, digital_only=False, modes=None):
        self.alias = ""
        self.devtype = DO
        self.circuit = circuit
        self.arm = arm
        self.modes = modes if modes is not None else ['Simple']
        # Soft-pwm
        self.pwmpresetreg = pwmpresetreg
        self.pwmcustompresc = pwmcustompresc
        # Hard-pwm
        self.pwmcyclereg = pwmcyclereg
        self.pwmprescalereg = pwmprescalereg
        self.pwmdutyreg = pwmdutyreg
        self.pwm_duty = None
        self.pwm_duty_val = None
        self.pwm_freq = None
        self.pwm_cycle_val = None
        self.pwm_prescale_val = None
        self.pwm_delay_val = None
        self.mode = None
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.digital_only = digital_only
        self.coil = coil
        self.valreg = reg
        self.bitmask = mask
        self.regvalue = lambda: self.arm.cache.get_register(1, self.valreg)[0]
        self.value = None
        self.block_pwm = False

        self.preset_map = {0: 1000, 1:100, 2:0}

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
        ret =  {'dev': 'do',
                'circuit': self.circuit,
                'value': self.value,
                'pending': self.pending_task is not None,
                'mode': self.mode,
                'modes': self.modes,
                }
        if self.digital_only:
            ret['pwm_freq'] = self.pwm_freq
            ret['pwm_duty'] = self.pwm_duty
        if self.alias != '':
            ret['alias'] = self.alias
        if forced_value is not None:
            ret['value'] = forced_value
        return ret

    def simple(self):
        return {'dev': 'do',
                'circuit': self.circuit,
                'value': self.value}

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value, self.pending_task is not None)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        if self.pending_task is not None:
            self.pending_task.cancel()
            self.pending_task = None
        await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return 1 if value else 0

    async def check_new_data(self):
        is_change = False
        if self.pwmdutyreg >= 0:  # This instance supports PWM mode
            if not self.block_pwm:
                if self.pwmpresetreg >=0:
                    old_prescale_val = copy(self.pwm_prescale_val)
                    old_cycle_val = copy(self.pwm_cycle_val)
                    self.pwm_prescale_val = (self.arm.cache.get_register(1, self.pwmpresetreg))[0]
                    self.pwm_cycle_val = (self.arm.cache.get_register(1, self.pwmcustompresc))[0]
                    if old_prescale_val != self.pwm_prescale_val or old_cycle_val != self.pwm_cycle_val:
                        if (self.pwm_prescale_val in self.preset_map) and self.preset_map[self.pwm_prescale_val] != 0:
                            self.pwm_freq = self.preset_map[self.pwm_prescale_val]
                        else:
                            self.pwm_freq = round(1000 / (1 + self.pwm_cycle_val),1)
                        is_change = True

                else:
                    old_cycle_val = copy(self.pwm_cycle_val)
                    old_prescale_val = copy(self.pwm_prescale_val)

                    self.pwm_cycle_val = ((self.arm.cache.get_register(1, self.pwmcyclereg))[0] + 1)
                    self.pwm_prescale_val = ((self.arm.cache.get_register(1, self.pwmprescalereg))[0] + 1)

                    if (old_cycle_val != self.pwm_cycle_val) or (old_prescale_val != self.pwm_prescale_val):
                        is_change = True
                        if (self.pwm_cycle_val > 0) and (self.pwm_prescale_val > 0):
                            self.pwm_freq = 48000000 / (self.pwm_cycle_val * self.pwm_prescale_val)
                        else:
                            self.pwm_freq = 0

                # PWM duty_val handling is almost same for both soft and hard PWM
                old_duty_val = copy(self.pwm_duty_val)
                self.pwm_duty_val = (self.arm.cache.get_register(1, self.pwmdutyreg))[0]
                if is_change or old_duty_val != self.pwm_duty_val:
                    is_change = True
                    if self.pwm_duty_val == 0:
                        self.pwm_duty = 0
                        self.mode = 'Simple'  # Mode field is for backward compatibility, will be deprecated soon
                    elif self.pwmpresetreg >=0:
                        self.pwm_duty = self.pwm_duty_val
                        self.mode = 'PWM'  # Mode field is for backward compatibility, will be deprecated soon
                    else:
                        self.pwm_duty = round((float(self.pwm_duty_val) / float(self.pwm_cycle_val)) * 100, 1)
                        self.mode = 'PWM'  # Mode field is for backward compatibility, will be deprecated soon

        else:  # This RELAY instance does not support PWM mode (no pwmdutyreg given)
            self.mode = 'Simple'

        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
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

            #if pwm_duty is not None and self.mode == 'PWM' and float(pwm_duty) <= 0.01:
            #    mode = 'Simple'
            # New system - mode field will no longer be used

            # Set PWM Freq
            if (pwm_freq is not None) and (pwm_freq > 0):
                self.block_pwm = True

                # Soft PWM
                if self.pwmpresetreg >=0:
                    pwm_preset_val = 0
                    if pwm_freq in self.preset_map.values():
                        pwm_preset_val = [preset for preset, freq in self.preset_map.items() if freq == pwm_freq][0]
                        await self.arm.client.write_single_register(self.pwmpresetreg, pwm_preset_val)
                    else:
                        pwm_prescaler = round((1000 / pwm_freq) - 1)
                        if pwm_prescaler < 0:
                            raise ValueError("Frequency out of range!")
                        self.pwm_freq = round(1000 / (1 + pwm_prescaler),1)
                        await self.arm.client.write_single_register(self.pwmpresetreg, 2)
                        await self.arm.client.write_single_register(self.pwmcustompresc, pwm_prescaler)

                    other_devs = {dev: dev.pwm_duty for dev in Devices.by_int(DO, major_group=self.major_group)}

                    for other_dev, other_pwm_duty in other_devs.items():
                        other_dev.pwm_freq = self.pwm_freq

                else:
                    tmp_pwm_delay_val = 48000000 / pwm_freq
                    if ((int(tmp_pwm_delay_val) % 50000) == 0) and ((tmp_pwm_delay_val / 50000) < 65535):
                        tmp_pwm_cycle_val = 50000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 50000)
                    elif ((int(tmp_pwm_delay_val) % 10000) == 0) and ((tmp_pwm_delay_val / 10000) < 65535):
                        tmp_pwm_cycle_val = 10000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 10000)
                    elif ((int(tmp_pwm_delay_val) % 5000) == 0) and ((tmp_pwm_delay_val / 5000) < 65535):
                        tmp_pwm_cycle_val = 5000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 5000)
                    elif ((int(tmp_pwm_delay_val) % 1000) == 0) and ((tmp_pwm_delay_val / 1000) < 65535):
                        tmp_pwm_cycle_val = 1000
                        tmp_pwm_prescale_val = round(tmp_pwm_delay_val / 1000)
                    else:
                        tmp_pwm_prescale_val = round(sqrt(tmp_pwm_delay_val))
                        tmp_pwm_cycle_val = round(tmp_pwm_prescale_val)
                    other_devs = {dev: float(dev.pwm_duty) for dev in Devices.by_int(DO, major_group=self.major_group)}

                    await self.arm.client.write_single_register(self.pwmcyclereg, tmp_pwm_cycle_val - 1)
                    await self.arm.client.write_single_register(self.pwmprescalereg, tmp_pwm_prescale_val - 1)

                    for other_dev, other_pwm_duty in other_devs.items():
                        other_dev.pwm_freq = pwm_freq
                        other_dev.pwm_delay_val = tmp_pwm_delay_val
                        other_dev.pwm_cycle_val = tmp_pwm_cycle_val
                        other_dev.pwm_prescale_val = tmp_pwm_prescale_val
                        if other_dev.pwm_duty > 0 and other_dev is not self:
                            await other_dev.set(pwm_duty=other_pwm_duty)
                self.block_pwm = False

            # Set Binary value
            if value is not None:

                parsed_value = 1 if int(value) else 0

                if pwm_duty is not None:
                    if (pwm_duty == 100 and parsed_value == 1) or (pwm_duty == 0 and parsed_value == 0): # No conflict in this case
                        pass
                    else:
                        raise Exception('Set value conflict: Cannot set both value and pwm_duty at once.')

                if timeout is not None:
                    timeout = float(timeout)

                self.mode = 'Simple'
                await self.arm.client.write_single_coil(self.coil, parsed_value)
                if self.pwm_duty is not None and self.pwm_duty != 0:
                    self.pwm_duty = 0
                    await self.arm.client.write_single_register(self.pwmdutyreg, round(self.pwm_duty)) # Turn off PWM

            # Set PWM Duty
            elif pwm_duty is not None and 0.0 <= pwm_duty <= 100.0:
                if self.pwmpresetreg >= 0:
                    tmp_pwm_duty_val = round(pwm_duty)
                else:
                    tmp_pwm_duty_val = round(float(self.pwm_cycle_val) * pwm_duty / 100.0)
                if self.value != 0:
                    await self.arm.client.write_single_coil(self.coil, 0)
                await self.arm.client.write_single_register(self.pwmdutyreg, tmp_pwm_duty_val)
                self.mode = 'PWM'

            if alias is not None:
                Devices.set_alias(alias, self)

            if timeout is None:
                return self.full()

            async def timercallback():
                await asyncio.sleep(float(timeout))
                self.pending_task = None
                await self.arm.client.write_single_coil(self.coil, 0 if value else 1)

            self.pending_task = asyncio.create_task(timercallback())

            return self.full()

        except Exception as E:
            logger.error(f"Error in set DO: {E}")
            raise E

    def get(self):
        return self.full()


class Relay:

    def __init__(self, circuit, arm, coil, reg, mask, major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = RO
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.coil = coil
        self.valreg = reg
        self.bitmask = mask
        self.regvalue = lambda: self.arm.cache.get_register(1, self.valreg)[0]
        self.value = None
        self.block_pwm = False

        self.forced_changes = False  # force_immediate_state_changes

    def full(self, forced_value=None):
        ret = {'dev': 'ro',
               'circuit': self.circuit,
               'value': self.value,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        if forced_value is not None:
            ret['value'] = forced_value
        return ret

    def simple(self):
        return {'dev': 'ro',
                'circuit': self.circuit,
                'value': self.value}

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return 1 if value else 0

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        return old_value != self.value

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts """
        try:

            # Set Binary value
            if value is not None:
                parsed_value = 1 if int(value) else 0
                await self.arm.client.write_single_coil(self.coil, parsed_value)

            if alias is not None:
                Devices.set_alias(alias, self)

            return self.full()

        except Exception as E:
            logger.exception(f"Error in set RO: {E}")
            raise E

    def get(self):
        return self.full()


class OwPower(object):
    def __init__(self, circuit, arm, coil, major_group=0):
        self.alias = ""
        self.devtype = OWPOWER
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.coil = coil
        self.value = 0
        self.simple = self.full

    def full(self):
        ret = {'dev': 'owpower', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = bool(int(value))
            self.value = value
            await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return self.full()

    def get(self):
        return self.full()


class NvSave(object):
    def __init__(self, circuit, arm, coil, major_group=0):
        self.alias = ""
        self.devtype = NV_SAVE
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.coil = coil
        self.value = 0
        self.simple = self.full

    def full(self):
        ret = {'dev': 'nv_save', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = bool(int(value))
            self.value = value
            await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return self.full()

    def get(self):
        return self.full()


class ULED(object):
    def __init__(self, circuit, arm, post, reg, mask, coil, major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = LED
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.bitmask = mask
        self.valreg = reg
        self.regvalue = lambda: self.arm.cache.get_register(1, self.valreg)[0]
        self.coil = coil
        self.value = None

    def full(self):
        ret = {'dev': 'led', 'circuit': self.circuit, 'value': self.value}
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'led', 'circuit': self.circuit, 'value': self.value}

    def value_delta(self, new_val):
        return (self.regvalue() ^ new_val) & self.bitmask

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        return old_value != self.value

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return 1 if value else 0

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = int(value)
            await self.arm.client.write_single_coil(self.coil, 1 if value else 0)
        return self.full()

    def get(self):
        return self.full()

class DigitalInput:
    def __init__(self, circuit, arm, reg, mask, regcounter=None, regdebounce=None, regmode=None, regtoggle=None, regpolarity=None,
                 major_group=0, modes=['Simple'], ds_modes=['Simple'], counter_modes=['Enabled', 'Disabled'], legacy_mode=True):
        self.alias = ""
        self.devtype = DI
        self.circuit = circuit
        self.arm = arm
        self.modes = modes
        self.ds_modes = ds_modes
        self.counter_modes = counter_modes
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.bitmask = mask
        self.regcounter = regcounter
        self.regdebounce = regdebounce
        self.regmode = regmode
        self.regtoggle = regtoggle
        self.regpolarity = regpolarity
        self.reg = reg
        self.regvalue = lambda: self.arm.cache.get_register(1, self.reg)[0]
        self.regcountervalue = self.regdebouncevalue = lambda: None
        if regcounter is not None:
            self.regcountervalue = lambda: self.arm.cache.get_register(1, regcounter)[0] + (self.arm.cache.get_register(1, regcounter + 1)[0] << 16)
        if regdebounce is not None:
            self.regdebouncevalue = lambda: self.arm.cache.get_register(1, regdebounce)[0]
        self.mode = 'Simple'
        self.ds_mode = 'Simple'
        self.counter_mode = "Enabled"
        self.value = None
        self.counter = None
        self.debounce = None

    async def check_new_data(self):
        if 'DirectSwitch' in self.modes:
            curr_ds = self.arm.cache.get_register(1, self.regmode)[0]
            if (curr_ds & self.bitmask) > 0:
                self.mode = 'DirectSwitch'
                curr_ds_pol = self.arm.cache.get_register(1, self.regpolarity)[0]
                curr_ds_tgl = self.arm.cache.get_register(1, self.regtoggle)[0]
                if curr_ds_pol & self.bitmask:
                    self.ds_mode = 'Inverted'
                elif curr_ds_tgl & self.bitmask:
                    self.ds_mode = 'Toggle'
                else:
                    self.ds_mode = 'Simple'
            else:
                self.mode = "Simple"

        old_value = copy(self.value)
        old_counter = copy(self.counter)
        self.value = 1 if (self.regvalue() & self.bitmask) else 0
        self.counter = self.regcountervalue()
        self.debounce = self.regdebouncevalue()
        return old_counter != self.counter or old_value != self.value

    def full(self):
        ret = {'dev': 'di',
               'circuit': self.circuit,
               'value': self.value,
               'debounce': self.debounce,
               'counter_modes': self.counter_modes,
               'counter_mode': self.counter_mode,
               'counter': self.counter if self.counter_mode == 'Enabled' else 0,
               'mode': self.mode,
               'modes': self.modes,
               }
        if self.mode == 'DirectSwitch':
            ret['ds_mode'] = self.ds_mode
            ret['ds_modes'] = self.ds_modes
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        if self.counter_mode == 'Enabled':
            return {'dev': 'di',
                    'circuit': self.circuit,
                    'value': self.value,
                    'counter': self.counter}
        else:
            return {'dev': 'di',
                    'circuit': self.circuit,
                    'value': self.value}

    async def write_config_register(self, reg, value):
        """ Write register and update the cache, so check_new_data does not see a stale value """
        await self.arm.client.write_single_register(reg, value)
        self.arm.cache.set_register(reg, [value])

    async def set(self, debounce=None, mode=None, counter=None, counter_mode=None, ds_mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        # Decide by the requested values and always read-modify-write the registers:
        # self.mode and self.ds_mode can be stale or rewritten by check_new_data()
        # in the scan task while this coroutine awaits.
        if mode not in self.modes:
            mode = self.mode
        else:
            self.mode = mode
            if mode == 'DirectSwitch':
                curr_ds = await self.arm.cache.get_register_async(1, self.regmode)
                curr_ds_val = curr_ds[0]
                curr_ds_val = curr_ds_val | int(self.bitmask)
                await self.write_config_register(self.regmode, curr_ds_val)
            else:
                curr_ds = await self.arm.cache.get_register_async(1, self.regmode)
                curr_ds_val = curr_ds[0]
                curr_ds_val = curr_ds_val & (~int(self.bitmask))
                await self.write_config_register(self.regmode, curr_ds_val)

        if mode == 'DirectSwitch' and ds_mode is not None and ds_mode in self.ds_modes:
            self.ds_mode = ds_mode
            curr_ds_pol = await self.arm.cache.get_register_async(1, self.regpolarity)
            curr_ds_tgl = await self.arm.cache.get_register_async(1, self.regtoggle)
            curr_ds_pol_val = curr_ds_pol[0]
            curr_ds_tgl_val = curr_ds_tgl[0]
            if ds_mode == 'Inverted':
                curr_ds_pol_val = curr_ds_pol_val | self.bitmask
                curr_ds_tgl_val = curr_ds_tgl_val & (~self.bitmask)
            elif ds_mode == 'Toggle':
                curr_ds_pol_val = curr_ds_pol_val & (~self.bitmask)
                curr_ds_tgl_val = curr_ds_tgl_val | self.bitmask
            else:
                curr_ds_pol_val = curr_ds_pol_val & (~self.bitmask)
                curr_ds_tgl_val = curr_ds_tgl_val & (~self.bitmask)
            await self.write_config_register(self.regpolarity, curr_ds_pol_val)
            await self.write_config_register(self.regtoggle, curr_ds_tgl_val)

        if counter_mode is not None and counter_mode in self.counter_modes and counter_mode != self.counter_mode:
            self.counter_mode = counter_mode

        if debounce is not None:
            if self.regdebounce is not None:
                await self.write_config_register(self.regdebounce, int(float(debounce)))
        if counter is not None:
            if self.regcounter is not None:
                await self.arm.client.write_uint32(self.regcounter, int(float(counter)))
        return self.full()

    def get(self):
        """ Returns ( value, debounce )
              current on/off value is taken from last value without reading it from hardware
        """
        return self.value, self.debounce

    def get_value(self):
        """ Returns value
              current on/off value is taken from last value without reading it from hardware
        """
        return self.value

class Watchdog(object):
    def __init__(self, circuit, arm, post, reg, timeout_reg, nv_save_coil=-1, reset_coil=-1, wd_reset_ro_coil=-1,
                 major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = WATCHDOG
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.timeoutvalue = lambda: self.arm.cache.get_register(1, self.toreg)
        self.regvalue = lambda: self.arm.cache.get_register(1, self.valreg)[0]
        self.nvsavvalue = 0
        self.resetvalue = 0
        self.nv_save_coil = nv_save_coil
        self.reset_coil = reset_coil
        self.wd_reset_ro_coil = wd_reset_ro_coil
        self.wdwasresetvalue = 0
        self.valreg = reg
        self.toreg = timeout_reg

        self.value = None
        self.timeout = None
        self.was_wd_boot_value = None

    def full(self):
        ret = {'dev': 'wd',
               'circuit': self.circuit,
               'value': self.value,
               'timeout': self.timeout,
               'was_wd_reset': self.was_wd_boot_value,
               'nv_save' :self.nvsavvalue,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def get(self):
        return self.full()

    def simple(self):
        return {'dev': 'wd',
                'circuit': self.circuit,
                'value': self.value}

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = self.regvalue() & 0x03  # Only the two lowest bits contains watchdog status
        self.timeout = self.timeoutvalue()[0] if self.timeoutvalue() else 0
        self.was_wd_boot_value = 1 if self.regvalue() & 0b10 else 0
        return old_value != self.value

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value, self.timeout)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.client.write_single_register(self.valreg, 1 if value else 0)
        return 1 if value else 0

    async def set(self, value=None, timeout=None, reset=None, nv_save=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)

        if value is not None:
            value = int(value)
            await self.arm.client.write_single_register(self.valreg, 1 if value else 0)

        if timeout is not None:
            timeout = int(timeout)
            if timeout > 65535:
                timeout = 65535
            await self.arm.client.write_single_register(self.toreg, timeout)

        if self.nv_save_coil >= 0 and nv_save is not None and nv_save != self.nvsavvalue:
            if nv_save != 0:
                self.nvsavvalue = 1
            else:
                self.nvsavvalue = 0
            await self.arm.client.write_single_coil(self.nv_save_coil, 1)

        if self.reset_coil >= 0 and reset is not None:
            if reset != 0:
                self.nvsavvalue = 0
                await self.arm.client.write_single_coil(self.reset_coil, 1)
                logger.info("Performed reset of board %s" % self.circuit)

        return self.full()

