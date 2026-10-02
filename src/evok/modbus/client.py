#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 13:40:31 2026

@author: bokula
"""
import struct

from typing import Literal
from tmodbus import (
    AsyncModbusClient
)
from tmodbus.utils.order_aware_struct import OrderAwareStruct

from .cache import ModbusCacheMap
from ..devices import devents
from ..log import logger

FLOAT32_BE = OrderAwareStruct(">f")
FLOAT32_LE = OrderAwareStruct(">f", word_order="little")
INT32_BE = OrderAwareStruct(">i")
INT32_LE = OrderAwareStruct(">i", word_order="little")
UINT32_BE = OrderAwareStruct(">I")
UINT32_LE = OrderAwareStruct(">I", word_order="little")
INT16 = OrderAwareStruct(">h")

FLOAT32_WORD_ORDER = {"big": FLOAT32_BE, "little": FLOAT32_LE}
UINT32_WORD_ORDER = {"big": UINT32_BE, "little": UINT32_LE}
INT32_WORD_ORDER = {"big": INT32_BE, "little": INT32_LE}


def from_registers(fmt: struct.Struct, registers):
    """ Decode a value from a list of 16-bit registers """
    return fmt.unpack(struct.pack(f">{len(registers)}H", *registers))[0]


def to_registers(fmt: struct.Struct, value):
    """ Encode a value into a list of 16-bit registers """
    data = fmt.pack(value)
    return list(struct.unpack(f">{len(data) // 2}H", data))


class Client:

    def __init__(self, name: str,
                 mb_client: AsyncModbusClient,
                 cache: ModbusCacheMap):
        self.name = name
        self.cache = cache
        self.mb_client = mb_client
        self.eventable_devices = []

    def read_u16(self, index: int, is_input: bool = False) -> int:
        """ Return the cached value of a 16-bit register """
        return self.cache.get_register(1, index, is_input=is_input)[0]

    def read_i16(self, index: int, is_input: bool = False) -> int:
        """ Return the cached value of a 16-bit register as signed int"""
        return from_registers(INT16, self.cache.get_register(1, index, is_input=is_input))

    def read_float32(self, index: int, is_input: bool = False,
                     word_order: Literal["big", "little"] = "little") -> float:
        """ Return the cached value of a 32-bit float in two registers,
            word_order "little" = low word first, "big" = high word first
        """
        return self._read32(FLOAT32_WORD_ORDER, index, is_input, word_order)

    def read_u32(self, index: int, is_input: bool = False,
                 word_order: Literal["big", "little"] = "little") -> int:
        """ Return the cached value of a 32-bit unsigned integer in two registers,
            word_order "little" = low word first, "big" = high word first
        """
        return self._read32(UINT32_WORD_ORDER, index, is_input, word_order)

    def read_i32(self, index: int, is_input: bool = False,
                 word_order: Literal["big", "little"] = "little") -> int:
        """ Return the cached value of a 32-bit signed integer in two registers,
            word_order "little" = low word first, "big" = high word first
        """
        return self._read32(INT32_WORD_ORDER, index, is_input, word_order)

    def _read32(self, formats: dict, index: int, is_input: bool, word_order: str):
        fmt = formats.get(word_order)
        if fmt is None:
            raise ValueError(f"Unknown word order '{word_order}'")
        return from_registers(fmt, self.cache.get_register(2, index, is_input=is_input))

    async def do_scan(self):

        if not await self.cache.do_scan():
            return False
        changeset = []
        for device in self.eventable_devices:
            try:
                if await device.check_new_data() is True:
                    changeset.append(device)
            except Exception as E:
                m = (f"Error while checking new data in device '{device.devtype}"
                     f"_{device.circuit}': {E}")
                logger.exception(m)

        if len(changeset) > 0:
            proxy = Proxy(set(changeset))
            devents.status(proxy)
        return True


class Proxy(object):
    def __init__(self, changeset):
        self.changeset = changeset

    def full(self):
        self.result = [c.full() for c in self.changeset]
        self.full = self.fullcache
        return self.result

    def fullcache(self):
        return self.result
