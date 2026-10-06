#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:46:51 2026

@author: bokula
"""
from math import isnan

from ..devices import AI, AO, REGISTER, DATA_POINT
from ..log import logger
from .cache import ENoCacheRegister
from .base import IODevice
from .client import Client, Accessor, Accessor32, AccessorBit, AccessorFactory
from .iomode import IOMode, WithIOMode


class AnalogInput(WithIOMode, IODevice):

    devtype = AI

    def __init__(self, circuit, client: Client, reg, regmode=None, major_group=0, modes=None):
        super().__init__(circuit, client, major_group)
        self.iomode = IOMode(client, regmode, modes, f"{self.devtype.upper()} {circuit}")
        self.value = None
        self.accessor = self._default_accessor(reg)

    @staticmethod
    def _default_accessor(reg) -> Accessor:
        """ Return the accessor used before a mode is known """
        return AccessorFactory.get(reg, 'float32', decimals=3)

    def _make_accessor(self) -> Accessor:
        """ Return the accessor of the value in the current mode """
        if self.mode is None:
            return Accessor(self.accessor.index, self.accessor.is_input)
        transformation = self.iomode.data.get('transformation', {})
        datatype = transformation.get("datatype", "float32")
        decimals = transformation.get("decimals", 3 if datatype == "float32" else None)
        logger.debug(f"Applying transformation on analog input {self.circuit}: {datatype} {decimals}")
        return self.accessor.refactor(datatype, ratio=transformation.get("ratio", 1),
                                      decimals=decimals)

    async def check_new_data(self):
        has_changed = self.iomode.update()
        if has_changed:
            self.accessor = self._make_accessor()

        old_value = self.value
        try:
            self.value = self.accessor.read(self.client)
        except ENoCacheRegister:
            self.value = None
        return self.value != old_value or has_changed

    async def set(self, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            await self.iomode.set(mode)
        return self.full()

    def full(self):
        ret = {'dev': self.devtype,
               'circuit': self.circuit,
               'value': self.value,
               'unit': self.unit_name,
               'mode': self.mode,
               'modes': self.modes,
               'range': self.range,
               }
        self._with_alias(ret)
        return ret


class AnalogOutput(AnalogInput):

    devtype = AO

    def __init__(self, circuit, client: Client, reg, regmode=None, modes=None, major_group=0):
        super().__init__(circuit, client, reg, regmode=regmode, major_group=major_group, modes=modes)

    @staticmethod
    def _default_accessor(reg) -> Accessor:
        return AccessorFactory.get(reg, 'uint16', ratio=0.0025, decimals=3)

    def _make_accessor(self) -> Accessor:
        """ The scaling of the output value does not depend on the mode """
        return self.accessor

    async def set_value(self, value):
        """ The value is clamped to the 12-bit range of the output, return the value written """
        value = min(max(float(value), 0.0), 4095 * self.accessor.ratio)
        await self.accessor.write(self.client, value)
        return self.accessor.read(self.client)

    async def set(self, value=None, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            await self.iomode.set(mode)

        if value is not None:
            await self.set_value(value)
        return self.full()


class AnalogOutputBrain(AnalogInput):

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
        super().__init__(circuit, client, reg, regmode=regmode, major_group=major_group,
                         modes=AnalogOutputBrain.modes)
        self.ao_accessor = AccessorFactory.get(reg, 'float32', decimals=3)
        self.res_accessor = AccessorFactory.get(reg_res, 'float32', decimals=3)

    def _make_accessor(self) -> Accessor:
        return self.res_accessor if self.mode == "Resistance" else self.ao_accessor

    async def set_value(self, value: float):
        if self.range is None:
            raise ValueError(f'AO {self.circuit}: unknown mode, cannot set the value')
        low, high = self.range
        if low > value or value > high:
            raise ValueError(f'AO {self.circuit}: value "{value}" is out of limit <{low}..{high}>')

        await self.ao_accessor.write(self.client, value)
        return value

    async def set(self, value=None, mode=None, alias=None):
        self.set_alias(alias)

        if mode is not None:
            await self.iomode.set(mode)
            self.iomode.mode = mode
            if mode in ("Voltage", "Current") and value is None:
                value = 0  # Set 0 after mode change
        if value is not None:
            if self.iomode.mode not in ("Voltage", "Current"):
                raise ValueError(f'AO {self.circuit}: value cannot be set in mode "{self.iomode.mode}"')
            await self.set_value(float(value))

        return self.full()


class DataPoint(IODevice):

    devtype = DATA_POINT

    def __init__(self, circuit, client: Client, reg, reg_type=None, major_group=0, datatype=None, unit=None,
                 offset=0, factor=1, name=None, writable=False):
        super().__init__(circuit, client, major_group)
        self.unit = unit
        self.name = name
        self.writable = writable
        self.value = None
        self.accessor = self._make_accessor(reg, reg_type == "input", datatype, factor, offset)

    def _make_accessor(self, reg, is_input, datatype, factor, offset):
        """ 16-bit datatypes are signed by default, 32-bit ones are high word first """
        datatype = datatype or 'signed16'
        accessor_cls = AccessorFactory.accessor_classes.get(datatype)
        word_order = 'big' if accessor_cls is not None and issubclass(accessor_cls, Accessor32) else None
        return AccessorFactory.get(reg, datatype, is_input=is_input, ratio=factor,
                                   offset=offset, word_order=word_order)

    async def check_new_data(self):
        old_value = self.value
        self.value = self.read_value()
        return old_value != self.value

    def read_value(self):
        try:
            value = self.accessor.read(self.client)
        except ENoCacheRegister:
            return None
        if isinstance(value, float) and isnan(value):
            return 'NaN'
        return value

    async def set(self, value=None, alias=None, **kwargs):
        """ Write the value with the inverse transformation of the datatype,
            only a writable data point in a holding register can be written
        """
        if value is not None:
            if not self.writable:
                raise ValueError(f"Data point {self.circuit} is read-only")
            await self.accessor.write(self.client, float(value))
        self.set_alias(alias)
        return self.full()

    def full(self):

        ret = {'dev': 'data_point',
               'circuit': self.circuit,
               'value': self.value,
               }

        if self.name is not None:
            ret['name'] = self.name

        if self.unit is not None:
            ret['unit'] = self.unit

        self._with_alias(ret)
        return ret


class Register(DataPoint):
    """ Raw 16-bit register """

    devtype = REGISTER

    def __init__(self, circuit, client: Client, reg, reg_type="holding", major_group=0):
        super().__init__(circuit, client, reg, reg_type=reg_type, major_group=major_group, datatype='uint16',
                         writable=True)

    def full(self):
        ret = {'dev': 'register',
               'circuit': self.circuit,
               'value': self.value,
               }
        self._with_alias(ret)
        return ret


class OwTemperature(DataPoint):
    """ Data point with a validity bit in a mask register (OneWire thermometer on xG18) """

    def __init__(self, circuit, client: Client, reg, valid_mask_reg, valid_mask, **kwargs):
        super().__init__(circuit, client, reg, **kwargs)
        self.accessor_valid = AccessorBit(valid_mask_reg, valid_mask, is_input=self.accessor.is_input)
        self.is_valid = None

    async def check_new_data(self):
        value_changed = await super().check_new_data()
        old_valid = self.is_valid
        self.is_valid = self.read_is_valid()
        return value_changed or old_valid != self.is_valid

    def read_is_valid(self):
        try:
            return bool(self.accessor_valid.read(self.client))
        except ENoCacheRegister:
            return False

    def full(self):
        ret = super().full()
        ret['valid'] = self.is_valid
        return ret
