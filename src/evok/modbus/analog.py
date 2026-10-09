#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from math import isfinite, isnan

from ..devices import AI, AO, REGISTER, DATA_POINT, to_float
from ..log import logger
from .cache import ENoCacheRegister
from .base import IODevice
from .client import Client, Accessor, Accessor32, AccessorBit, AccessorFactory
from .iomode import IOMode, WithIOMode


def non_finite_to_str(value):
    """ NaN and infinity are not valid JSON, NaN is not equal to itself, it would be an event on every scan """
    if isinstance(value, float) and not isfinite(value):
        return 'NaN' if isnan(value) else 'Infinity' if value > 0 else '-Infinity'
    return value


class AnalogInput(WithIOMode, IODevice):

    devtype = AI

    def __init__(self, circuit, client: Client, reg, regmode=None, major_group=0, modes=None):
        super().__init__(circuit, client, major_group)
        # an unknown datatype was found by the first read in the mode, the value was null with a warning
        for mode, data in (modes or {}).items():
            datatype = data.get('transformation', {}).get('datatype', 'float32')
            if datatype not in AccessorFactory.accessor_classes:
                raise ValueError(f'{self.devtype.upper()} {circuit}: unknown datatype "{datatype}" of mode "{mode}"')
        self.iomode = IOMode(client, regmode, modes, f"{self.devtype.upper()} {circuit}")
        self.value = None
        self.accessor = self._default_accessor(reg)
        self.accessor_mode = None   # the mode of the accessor, the default one is used before a mode is known

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
                                      offset=transformation.get("offset", 0), decimals=decimals)

    async def check_new_data(self):
        has_changed = self.iomode.update()
        # a fixed mode without a mode register is known before the first update
        if has_changed or self.mode != self.accessor_mode:
            self.accessor = self._make_accessor()
            self.accessor_mode = self.mode

        old_value = self.value
        try:
            self.value = non_finite_to_str(self.accessor.read(self.client))
        except ENoCacheRegister:
            self.value = None
        return self.value != old_value or has_changed

    async def set(self, mode=None, alias=None):
        if mode is not None:
            await self.iomode.set(mode)
        self.set_alias(alias)

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

    def _check_value(self, value, mode) -> float:
        """ Return the value as a float, it must be in the range of the mode,
            without a range in the 12-bit range of the output
        """
        value = to_float(value)
        low, high = self.iomode.modes.get(mode, {}).get('range') or (0.0, 4095 * self.accessor.ratio)
        if not low <= value <= high:
            raise ValueError(f'AO {self.circuit}: value "{value}" is out of limit <{low}..{high}>')
        return value

    async def set_value(self, value):
        """ Set the value in the current mode, return the value written, it is used also by RPC """
        value = self._check_value(value, self.iomode.mode)
        await self.accessor.write(self.client, value)
        return self.accessor.read(self.client)

    async def set(self, value=None, mode=None, alias=None):
        """ All params are validated before the first write, the value is checked in the new mode """
        if mode is not None:
            self.iomode.check(mode)
        if value is not None:
            value = self._check_value(value, mode if mode is not None else self.iomode.mode)

        if mode is not None:
            await self.iomode.set(mode)
        if value is not None:
            await self.accessor.write(self.client, value)
        self.set_alias(alias)


class AnalogOutputBrain(AnalogInput):

    devtype = AO

    MODES = {
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

    def __init__(self, circuit, client: Client, reg, regmode=None, reg_res=None, major_group=0):
        """ Without reg_res, the register of the measured resistance, the Resistance mode is not available """
        modes = self.MODES if reg_res is not None else \
            {mode: data for mode, data in self.MODES.items() if mode != 'Resistance'}
        super().__init__(circuit, client, reg, regmode=regmode, major_group=major_group, modes=modes)
        self.ao_accessor = AccessorFactory.get(reg, 'float32', decimals=3)
        self.res_accessor = AccessorFactory.get(reg_res, 'float32', decimals=3) if reg_res is not None \
            else Accessor(None)

    def _make_accessor(self) -> Accessor:
        return self.res_accessor if self.mode == "Resistance" else self.ao_accessor

    def _check_value(self, value, mode) -> float:
        """ The value can be set only in the Voltage and Current modes, return it as a float """
        if mode not in ("Voltage", "Current"):
            raise ValueError(f'AO {self.circuit}: value cannot be set in mode "{mode}"')
        value = to_float(value)
        low, high = self.iomode.modes[mode]['range']
        if low > value or value > high:
            raise ValueError(f'AO {self.circuit}: value "{value}" is out of limit <{low}..{high}>')
        return value

    async def set_value(self, value: float):
        """ Set the value in the current mode, return the value written, it is used also by RPC """
        value = self._check_value(value, self.iomode.mode)
        await self.ao_accessor.write(self.client, value)
        return self.ao_accessor.read(self.client)

    async def set(self, value=None, mode=None, alias=None):
        """ All params are validated before the first write, the value is checked
            in the new mode. A change of the mode to Voltage or Current sets 0 without
            a value, the current mode keeps the value.
        """
        new_mode = self.iomode.mode
        if mode is not None:
            self.iomode.check(mode)
            if mode != self.iomode.mode and mode in ("Voltage", "Current") and value is None:
                value = 0
            new_mode = mode
        if value is not None:
            value = self._check_value(value, new_mode)

        if mode is not None:
            await self.iomode.set(mode)
        if value is not None:
            await self.ao_accessor.write(self.client, value)
        self.set_alias(alias)


class DataPoint(IODevice):

    devtype = DATA_POINT

    def __init__(self, circuit, client: Client, reg, reg_type=None, major_group=0, datatype=None, unit=None,
                 offset=0, factor=1, name=None, writable=False):
        super().__init__(circuit, client, major_group)
        if writable and reg_type == "input":
            # it was found by the first write, an input register is read-only
            raise ValueError(f"Data point {circuit}: an input register cannot be writable")
        self.unit = unit
        self.name = name
        self.writable = writable
        self.value = None
        self.accessor = self._make_accessor(reg, reg_type == "input", datatype, factor, offset)

    def _make_accessor(self, reg, is_input, datatype, factor, offset):
        """ 16-bit datatypes are signed by default, 32-bit ones are high word first """
        datatype = datatype or 'signed16'
        accessor_cls = AccessorFactory.accessor_classes.get(datatype)
        if accessor_cls is None:
            raise ValueError(f'Data point {self.circuit}: unknown datatype "{datatype}"')
        word_order = 'big' if issubclass(accessor_cls, Accessor32) else None
        return AccessorFactory.get(reg, datatype, is_input=is_input, ratio=factor,
                                   offset=offset, word_order=word_order)

    async def check_new_data(self):
        old_value = self.value
        self.value = self.read_value()
        return old_value != self.value

    def read_value(self):
        try:
            return non_finite_to_str(self.accessor.read(self.client))
        except ENoCacheRegister:
            return None

    async def set(self, value=None, alias=None):
        """ Write the value with the inverse transformation of the datatype,
            only a writable data point in a holding register can be written
        """
        if value is not None:
            if not self.writable:
                raise ValueError(f"Data point {self.circuit} is read-only")
            await self.accessor.write(self.client, to_float(value))
        self.set_alias(alias)

    def full(self):

        ret = {'dev': 'data_point',
               'circuit': self.circuit,
               'value': self.value,
               'writable': self.writable,
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
        # a holding register is writable, an input one is read-only
        super().__init__(circuit, client, reg, reg_type=reg_type, major_group=major_group, datatype='uint16',
                         writable=reg_type != "input")

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
