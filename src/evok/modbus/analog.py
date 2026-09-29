#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:46:51 2026

@author: bokula
"""
import asyncio
import logging
import struct

from copy import copy
from math import sqrt, isnan
from typing import Union
from tmodbus.utils.order_aware_struct import OrderAwareStruct

from ..devices import MODBUS_SLAVE, \
                     DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
                     REGISTER, DATA_POINT, BOARD, NV_SAVE, Devices
from ..errors import ModbusSlaveError
from ..log import logger
from .cache import ModbusCacheMap, ENoCacheRegister
#from .builder import Board

FLOAT32_BE = OrderAwareStruct(">f")
FLOAT32_LE = OrderAwareStruct(">f", word_order="little")
INT32_LE = OrderAwareStruct(">i", word_order="little")
UINT32_LE = OrderAwareStruct(">I", word_order="little")


def from_registers(fmt: struct.Struct, registers):
    """ Decode a value from a list of 16-bit registers """
    return fmt.unpack(struct.pack(f">{len(registers)}H", *registers))[0]


def to_registers(fmt: struct.Struct, value):
    """ Encode a value into a list of 16-bit registers """
    data = fmt.pack(value)
    return list(struct.unpack(f">{len(data) // 2}H", data))


class Register:
    def __init__(self, circuit, arm, post, reg, reg_type="holding", major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = REGISTER
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.valreg = reg
        self.reg_type = reg_type

    def regvalue(self):
        try:
            if self.reg_type == "input":
                return self.arm.cache.get_register(1, self.valreg, is_input=True)[0]
            else:
                return self.arm.cache.get_register(1, self.valreg, is_input=False)[0]
        except ENoCacheRegister:
            return None

    def full(self):
        ret = {'dev': 'register',
               'circuit': self.circuit,
               'value': self.regvalue(),
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'register',
                'circuit': self.circuit,
                'value': self.regvalue()}

    @property
    def value(self):
        try:
            if self.regvalue():
                return self.regvalue()
        except:
            pass
        return 0


    def get(self):
        return self.full()

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return (self.value)

    async def set_state(self, value):
        """ Sets new on/off status. Disable pending timeouts
        """
        await self.arm.client.write_single_register(self.valreg, value if value else 0)
        return value if value else 0

    async def set(self, value=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)
        if value is not None:
            value = int(value)
            await self.arm.client.write_single_register(self.valreg, value if value else 0)

        return self.full()




class AnalogOutputBrain:
    def __init__(self, circuit, arm, reg, regmode=None, reg_res=0, major_group=0):
        self.alias = ""
        self.devtype = AO
        self.circuit = circuit
        self.reg = reg
        self.regmode = regmode
        self.reg_res = reg_res
        self.modes = {
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
            'Resistance':{
                'value': 2,
                'unit': 'Ohm',
                'range': [0, 2000]
            }
        }
        self.arm = arm
        self.major_group = major_group
        self.is_voltage = lambda: bool(self.arm.cache.get_register(1, self.regmode)[0] == 0)
        self.value = None
        self.res_value = None
        self.mode = None
        self.unit = None

    async def check_new_data(self):
        if self.is_voltage():
            self.mode = 'Voltage'
        elif self.arm.cache.get_register(1, self.regmode)[0] == 1:
            self.mode = 'Current'
        else:
            self.mode = 'Resistance'
        self.unit = self.modes[self.mode]['unit']

        old_value = copy(self.value)
        old_res_value = copy(self.res_value)
        self.value = self.regvalue()
        self.res_value = self.regres_value()
        return self.value != old_value or self.res_value != old_res_value

    def regvalue(self):
        try:
            regs = self.arm.cache.get_register(2, self.reg)
            ret = from_registers(FLOAT32_LE, regs)
            #ret = BinaryPayloadDecoder.fromRegisters(ret, Endian.BIG, Endian.LITTLE).decode_32bit_float()
            return round(float(ret), 3)
        except:
            return 0

    def regres_value(self):
        try:
            regs = self.arm.cache.get_register(2, self.reg_res)
            ret = from_registers(FLOAT32_LE, regs)
            #ret = BinaryPayloadDecoder.fromRegisters(ret, Endian.BIG, Endian.LITTLE).decode_32bit_float()
            return round(float(ret), 3)
        except:
            return 0

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'unit': self.unit
        }

        if self.mode == 'Resistance':
            ret['value'] = self.res_value
        else:
            ret['value'] = self.value
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        if self.mode == 'Resistance':
            return {'dev': 'ao',
                    'circuit': self.circuit,
                    'value': self.res_value}
        else:
            return {'dev': 'ao',
                    'circuit': self.circuit,
                    'value': self.value}

    async def set_value(self, value):
        if value < 0:
            value = 0
        # TODO: omezenit horni hodnoty!!!

        value_set = to_registers(FLOAT32_LE, float(value))
        #builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE)
        #builder.add_32bit_float(float(value))
        #value_set = builder.to_registers()

        await self.arm.client.write_multiple_registers(self.reg, values=value_set)
        return value

    async def set(self, value=None, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes and self.regmode is not None:
            val = self.arm.cache.get_register(1, self.regmode)[0]
            cur_val = self.value
            if mode == "Voltage":
                val = 0
            elif mode == "Current":
                val = 1
            elif mode == "Resistance":
                val = 3
            self.mode = mode
            await self.arm.client.write_single_register(self.regmode, val)
            if mode == "Voltage" or mode == "Current":
                await self.set_value(cur_val)        # Restore original value (i.e. 1.5V becomes 1.5mA)
        if not (value is None):
            await self.set_value(float(value))  # Restore original value (i.e. 1.5V becomes 1.5mA)
        return self.full()

    def get(self):
        return self.full()


class AnalogOutput:
    def __init__(self, circuit, arm, reg, regmode=None, modes=None, major_group=0):
        self.alias = ""
        self.devtype = AO
        self.circuit = circuit
        self.reg = reg
        self.regvalue = lambda: self.arm.cache.get_register(1, self.reg)[0]
        self.regmode = regmode
        self.modes = modes if modes is not None else {}
        self.arm = arm
        self.major_group = major_group
        self.offset = 0
        self.value = None
        self.res_value = None
        self.mode = list(modes.keys())[0] if len(modes) == 1 and self.regmode is None else None

    def get_mode_by_regvalue(self, regvalue: int):
        for mode, data in self.modes.items():
            if regvalue == data['value']:
                return mode
        return None

    @property
    def unit_name(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('unit', None)
        else:
            return None

    @property
    def range(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('range', None)
        else:
            return None

    async def check_new_data(self):
        if self.regmode is not None:
            mode_value = self.arm.cache.get_register(1, self.regmode)[0]
            self.mode = self.get_mode_by_regvalue(mode_value)

        old_value = copy(self.value)
        old_res_value = copy(self.res_value)
        self.value = round(self.regvalue() * 0.0025, 3)
        self.res_value = round(float(self.regvalue()) * 0.0025, 3)
        return self.value != old_value or self.res_value != old_res_value

    def full(self):
        ret = {'dev': 'ao',
               'circuit': self.circuit,
               'mode': self.mode,
               'modes': self.modes,
               'value': self.value,
               'unit': self.unit_name,
               'range': self.range,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'ao',
                'circuit': self.circuit,
                'value': self.value}

    async def set_value(self, value):
        valuei = int((float(value) / 0.0025))
        if valuei < 0:
            valuei = 0
        elif valuei > 4095:
            valuei = 4095
        await self.arm.client.write_single_register(self.reg, valuei)
        return float(valuei) * 0.0025

    async def set(self, value=None, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes and self.regmode is not None:
            mdata = self.modes[mode]
            if 'value' not in mdata:
                raise ValueError("AnalogOutput: this device cant switch mode!")
            mvalue = int(mdata['value'])
            await self.arm.client.write_single_register(self.regmode, mvalue)

        if not (value is None):
            await self.set_value(value)
        return self.full()

    def get(self):
        return self.full()


class AnalogInput:

    def __init__(self, circuit, arm, reg, regmode=None, major_group=0, legacy_mode=True, modes=None):
        self.alias = ""
        self.devtype = AI
        self.circuit = circuit
        self.valreg = reg
        self.arm = arm
        self.legacy_mode = legacy_mode
        self.regmode = regmode
        self.modes = modes if modes is not None else {}
        self.mode = list(modes.keys())[0] if len(modes) == 1 and self.regmode is None else None
        self.mode_value = None
        self.major_group = major_group
        self.is_voltage = lambda: True
        self.value = None
        self.transformation = lambda registers: \
              round(float(from_registers(FLOAT32_LE, registers)), 3)

        #logger.debug(f"AnalogInput.__init__ called, instance content {vars(self)}")

    def get_mode_by_regvalue(self, regvalue: int):
        for mode, data in self.modes.items():
            if regvalue == data['value']:
                return mode
        return None

    def reload_mode(self, mode_value: int):
        for mode, data in self.modes.items():
            if mode_value == data['value']:
                if data.get("transformation"):
                    #logger.debug(f"Mode: {data['value']} -> {data['transformation']}")
                    datatype = data["transformation"].get("datatype", "float32")
                    decimals = data["transformation"].get("decimals", 3)
                    ratio = data["transformation"].get("ratio", 1)
                    logger.debug(f"Aplying transformation on analog input {self.circuit}: {datatype}  {decimals}")
                    if datatype == "float32":
                        self.transformation = lambda registers:\
                            round(float(from_registers(FLOAT32_LE, registers)) * ratio, decimals)

                    elif datatype == "int32":
                        self.transformation = lambda registers:\
                            int(from_registers(INT32_LE, registers)) * ratio

                    elif datatype == "uint32" and isinstance(ratio, float) :
                        self.transformation = lambda registers:\
                            round(int(from_registers(UINT32_LE, registers)) * ratio, decimals)

                    elif datatype == "uint32":
                        self.transformation = lambda registers:\
                            int(from_registers(UINT32_LE, registers)) * ratio
                return mode
        return None

    @property
    def unit_name(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('unit', None)
        else:
            return None

    @property
    def range(self):
        if self.mode in self.modes:
            return self.modes[self.mode].get('range', None)
        else:
            return None

    async def check_new_data(self):
        has_changed = False
        if self.regmode is not None:
            old_mode_value = copy(self.mode_value)
            self.mode_value = self.arm.cache.get_register(1, self.regmode)[0]
            if old_mode_value != self.mode_value:
                self.mode = self.reload_mode(self.mode_value)
                has_changed = True

        old_value = copy(self.value)
        self.value = self.regvalue()
        return self.value != old_value or has_changed

    def regvalue(self):
        try:
            # TODO adaptive data length
            ret = self.arm.cache.get_register(2, self.valreg)
            return self.transformation(ret)
        except ENoCacheRegister:
            return None

    async def set(self, mode=None, alias=None):
        if alias is not None:
            Devices.set_alias(alias, self)

        if mode is not None and mode in self.modes:
            mdata = self.modes[mode]
            if 'value' not in mdata:
                raise ValueError("AnalogInput: this device cant switch mode!")
            mvalue = int(mdata['value'])
            await self.arm.client.write_single_register(self.regmode, mvalue)
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
        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def get(self):
        return self.full()

    def simple(self):
        return {'dev': 'ai',
                'circuit': self.circuit,
                'value': self.value}

    @property
    def voltage(self):
        return self.value

class DataPoint:

    def __init__(self, circuit, arm, reg, reg_type=None, major_group=0, datatype=None, unit=None, offset=0, factor=1, valid_mask_reg=None, valid_mask=None, name=None, post_write=None):
        # TODO - valid mask reg
        self.alias = ""
        self.devtype = DATA_POINT
        self.circuit = circuit
        self.arm = arm
        self.major_group = major_group
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
            val = self.arm.cache.get_register(1, self.valid_mask_reg, is_input=self.is_input)[0]
            return bool(val & self.valid_mask)
        except ENoCacheRegister:
            return 0

    def read_value(self):
        try:
            if self.datatype is None or self.datatype == "signed16":
                value = self.arm.cache.get_register(1, self.valreg, is_input=self.is_input)[0]
            elif self.datatype == "float32":
                value = self.__parse_float32(self.arm.cache.get_register(2, self.valreg, is_input=self.is_input))
            else:
                logger.warning(f"Data point: Unsupported datatype {self.datatype}")
                return None
            if self.factor == 1 and self.offset == 0:  # Reading RAW value - save some CPU time
                return value
            else:
                return (value * self.factor) + self.offset
        except ENoCacheRegister:
            return None

    def __parse_float32(self, raw_regs):
        ret = from_registers(FLOAT32_BE, raw_regs)
        #ret = float(BinaryPayloadDecoder.fromRegisters(raw_regs, Endian.BIG, Endian.BIG).decode_32bit_float())
        return ret if not isnan(ret) else 'NaN'

    async def set(self, value=None, alias=None, **kwargs):
        """ Sets new on/off status. Disable pending timeouts """
        if alias is not None:
            Devices.set_alias(alias, self)

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

        if self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return {'dev': 'data_point',
                'circuit': self.circuit,
                'value': self.read_value()}

    def get(self):
        return self.full()

    def get_state(self):
        """ Returns ( status, is_pending )
              current on/off status is taken from last mcp value without reading it from hardware
              is_pending is Boolean
        """
        return self.value

