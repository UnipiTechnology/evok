#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:46:51 2026

@author: bokula
"""
from copy import copy
from math import isnan

from ..devices import AI, AO, REGISTER, DATA_POINT
from ..log import logger
from .cache import ENoCacheRegister
from .base import IODevice
from .client import Client, FLOAT32_LE, to_registers
from .iomode import IOMode, WithIOMode


class Register(IODevice):

    devtype = REGISTER

    def __init__(self, circuit, client: Client, post, reg, reg_type="holding", major_group=0):
        super().__init__(circuit, client, major_group)
        self.valreg = reg
        self.reg_type = reg_type

    def regvalue(self):
        try:
            return self.client.read_u16(self.valreg, is_input=self.reg_type == "input")
        except ENoCacheRegister:
            return None

    def full(self):
        ret = {'dev': 'register',
               'circuit': self.circuit,
               'value': self.regvalue(),
               }
        self._with_alias(ret)
        return ret

    @property
    def value(self):
        try:
            if self.regvalue():
                return self.regvalue()
        except Exception:
            pass
        return 0

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        self.set_alias(alias)
        if value is not None:
            value = int(value)
            await self.client.mb_client.write_single_register(self.valreg, value if value else 0)

        return self.full()


class AnalogOutputBrain(WithIOMode, IODevice):

    devtype = AO

    modes = {
        'Voltage': {
            'value': 0,
            'unit': 'V',
            'range': [0, 10]
        },
        'Current': {
            'value': 1,
            'unit': 'mA',
            'range': [0, 20]
        },
        'Resistance': {
            'value': 3,
            'unit': 'Ohm',
            'range': [0, 2000]
        }
    }

    def __init__(self, circuit, client: Client, reg, regmode=None, reg_res=0, major_group=0):
        super().__init__(circuit, client, major_group)
        self.iomode = IOMode(client, regmode, AnalogOutputBrain.modes, f"AO {circuit}")
        self.reg = reg
        self.reg_res = reg_res
        self.value = None
        self.res_value = None

    async def check_new_data(self):
        has_changed = self.iomode.update()

        old_value = self.value
        old_res_value = self.res_value
        try:
            self.value = round(self.client.read_float32(self.reg), 3)
        except Exception:
            self.value = 0
        try:
            self.res_value = round(self.client.read_float32(self.reg_res), 3)
        except Exception:
            self.res_value = 0
        return self.value != old_value or self.res_value != old_res_value or has_changed

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'unit': self.unit_name,
               'value': self.value if self.mode != 'Resistance' else self.res_value
               }

        self._with_alias(ret)
        return ret

    async def set_value(self, value):
        if value < 0:
            value = 0
        # TODO: omezenit horni hodnoty!!!

        value_set = to_registers(FLOAT32_LE, float(value))

        await self.client.mb_client.write_multiple_registers(self.reg, values=value_set)
        return value

    async def set(self, value=None, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            cur_val = self.value
            await self.iomode.set(mode)
            # Report the new mode at once, mode_value is kept so the next scan still reports the change
            self.iomode.mode = mode
            if mode == "Voltage" or mode == "Current":
                await self.set_value(cur_val)        # Restore original value (i.e. 1.5V becomes 1.5mA)
        if value is not None:
            await self.set_value(float(value))  # Restore original value (i.e. 1.5V becomes 1.5mA)
        return self.full()


class AnalogOutput(WithIOMode, IODevice):

    devtype = AO

    def __init__(self, circuit, client: Client, reg, regmode=None, modes=None, major_group=0):
        super().__init__(circuit, client, major_group)
        self.iomode = IOMode(client, regmode, modes, f"AO {circuit}")
        self.reg = reg
        self.value = None

    async def check_new_data(self):
        has_changed = self.iomode.update()
        old_value = self.value
        try:
            self.value = round(self.client.read_u16(self.reg) * 0.0025, 3)
        except ENoCacheRegister:
            self.value = None
        return self.value != old_value or has_changed

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'value': self.value,
               'unit': self.unit_name,
               'range': self.range,
               }
        self._with_alias(ret)
        return ret

    async def set_value(self, value):
        valuei = int((float(value) / 0.0025))
        if valuei < 0:
            valuei = 0
        elif valuei > 4095:
            valuei = 4095
        await self.client.mb_client.write_single_register(self.reg, valuei)
        return float(valuei) * 0.0025

    async def set(self, value=None, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            await self.iomode.set(mode)

        if value is not None:
            await self.set_value(value)
        return self.full()


class AnalogInput(WithIOMode, IODevice):

    devtype = AI

    def __init__(self, circuit, client: Client, reg, regmode=None, major_group=0, modes=None):
        super().__init__(circuit, client, major_group)
        self.iomode = IOMode(client, regmode, modes, f"AI {circuit}")
        self.valreg = reg
        self.value = None
        self.transformation = lambda index: round(float(self.client.read_float32(index)), 3)

    def _make_transformation(self):
        """ Return the function reading the value in the current mode """
        if self.mode is None:
            return lambda index: None
        transformation = self.iomode.data.get('transformation', {})
        datatype = transformation.get("datatype", "float32")
        decimals = transformation.get("decimals", 3)
        ratio = transformation.get("ratio", 1)
        logger.debug(f"Aplying transformation on analog input {self.circuit}: {datatype}  {decimals}")
        if datatype == "float32":
            return lambda index: round(float(self.client.read_float32(index)) * ratio, decimals)
        elif datatype == "int32":
            return lambda index: self.client.read_i32(index) * ratio
        elif datatype == "uint32" and isinstance(ratio, float):
            return lambda index: round(float(self.client.read_u32(index)) * ratio, decimals)
        elif datatype == "uint32":
            return lambda index: int(self.client.read_u32(index) * ratio)
        logger.warning(f'Unknown datatype "{datatype}" in transformation for AI {self.circuit}')
        return lambda index: None

    async def check_new_data(self):
        has_changed = self.iomode.update()
        if has_changed:
            self.transformation = self._make_transformation()

        old_value = self.value
        try:
            self.value = self.transformation(self.valreg)
        except ENoCacheRegister:
            self.value = None
        return self.value != old_value or has_changed

    async def set(self, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            await self.iomode.set(mode)
        return self.full()

    def full(self):
        ret = {'dev': 'ai',
               'circuit': self.circuit,
               'value': self.value,
               'unit': self.unit_name,
               'mode': self.mode,
               'modes': self.modes,
               'range': self.range,
               }
        self._with_alias(ret)
        return ret


class DataPoint(IODevice):

    devtype = DATA_POINT

    def __init__(self, circuit, client: Client, reg, reg_type=None, major_group=0, datatype=None, unit=None,
                 offset=0, factor=1, valid_mask_reg=None, valid_mask=None, name=None, post_write=None):
        # TODO - valid mask reg
        super().__init__(circuit, client, major_group)
        self.valreg = reg
        self.offset = offset
        self.factor = factor
        self.unit = unit
        self.name = name
        self.post_write = post_write
        self.datatype = datatype
        self.valid_mask_reg = valid_mask_reg
        self.valid_mask = valid_mask
        self.is_input = reg_type == "input"
        self.is_valid = None
        self.value = None

    async def check_new_data(self):
        old_value = copy(self.value)
        old_valid_mask = copy(self.is_valid)
        self.value = self.read_value()
        self.is_valid = self.read_is_valid()
        return old_value != self.value or old_valid_mask != self.is_valid

    def read_is_valid(self):
        if self.valid_mask_reg is None:
            return 0
        try:
            val = self.client.read_u16(self.valid_mask_reg, is_input=self.is_input)
            return bool(val & self.valid_mask)
        except ENoCacheRegister:
            return 0

    def read_value(self):
        try:
            if self.datatype is None or self.datatype == "signed16":
                value = self.client.read_i16(self.valreg, is_input=self.is_input)
            elif self.datatype == "float32":
                value = self.client.read_float32(self.valreg, is_input=self.is_input, word_order="big")
                if isnan(value):
                    value = 'NaN'
            else:
                logger.warning(f"Data point: Unsupported datatype {self.datatype}")
                return None
            if self.factor == 1 and self.offset == 0:  # Reading RAW value - save some CPU time
                return value
            else:
                return (value * self.factor) + self.offset
        except ENoCacheRegister:
            return None

    async def set(self, value=None, alias=None, **kwargs):
        """ Sets new on/off status. Disable pending timeouts """
        self.set_alias(alias)

        raise Exception("Data point object is read-only")

    def full(self):

        ret = {'dev': 'data_point',
               'circuit': self.circuit,
               'value': self.value,
               }

        if self.name is not None:
            ret['name'] = self.name

        if self.valid_mask_reg is not None:
            ret['valid'] = self.is_valid

        if self.unit is not None:
            ret['unit'] = self.unit

        self._with_alias(ret)
        return ret
