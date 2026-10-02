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


class Reader:
    """ Reads a value of a given datatype from the cache of a Client
        and applies the linear transformation val * ratio + offset
        and rounding to decimals. Base class reads nothing (unknown datatype).
    """
    datatype = None

    def __init__(self, index: int, is_input: bool = False, *,
                 ratio=1, offset=0, decimals=None):
        self.index = index
        self.is_input = is_input
        self.ratio = ratio
        self.offset = offset
        self.decimals = decimals

    def params(self) -> dict:
        return dict(is_input=self.is_input, ratio=self.ratio,
                    offset=self.offset, decimals=self.decimals)

    def refactor(self, datatype: str = 'uint16', ratio=1, offset=0, decimals=None,
                 word_order=None) -> "Reader":
        """ Return a new reader of the same register. Only index and is_input
            are taken from this reader, the other parameters come from the call.
        """
        return ReaderFactory.get(self.index, datatype, is_input=self.is_input, ratio=ratio,
                                 offset=offset, decimals=decimals, word_order=word_order)

    def read_raw(self, client: Client) -> int | float | None:
        return None

    def read(self, client: Client) -> int | float | None:
        val = self.read_raw(client)
        if val is None:
            return None
        if self.ratio != 1 or self.offset != 0:
            val = val * self.ratio + self.offset
        if self.decimals is not None:
            val = round(val, self.decimals)
        return val


class ReaderU16(Reader):
    datatype = 'uint16'

    def read_raw(self, client: Client) -> int:
        return client.read_u16(self.index, is_input=self.is_input)


class ReaderI16(Reader):
    datatype = 'int16'

    def read_raw(self, client: Client) -> int:
        return client.read_i16(self.index, is_input=self.is_input)


class Reader32(Reader):
    """ Base for values in two registers, see Client.read_u32 for word_order """

    def __init__(self, index: int, is_input: bool = False, *,
                 word_order: Literal["big", "little"] = "little", **kwargs):
        if word_order not in ("big", "little"):
            raise ValueError(f"Unknown word order '{word_order}'")
        super().__init__(index, is_input, **kwargs)
        self.word_order = word_order

    def params(self) -> dict:
        return dict(super().params(), word_order=self.word_order)


class ReaderU32(Reader32):
    datatype = 'uint32'

    def read_raw(self, client: Client) -> int:
        return client.read_u32(self.index, is_input=self.is_input, word_order=self.word_order)


class ReaderI32(Reader32):
    datatype = 'int32'

    def read_raw(self, client: Client) -> int:
        return client.read_i32(self.index, is_input=self.is_input, word_order=self.word_order)


class ReaderFloat32(Reader32):
    datatype = 'float32'

    def read_raw(self, client: Client) -> float:
        return client.read_float32(self.index, is_input=self.is_input, word_order=self.word_order)


class ReaderFactory:
    reader_classes = {
        'uint16': ReaderU16,
        'int16': ReaderI16,
        'signed16': ReaderI16,  # name used by data_point in hw definitions
        'uint32': ReaderU32,
        'int32': ReaderI32,
        'float32': ReaderFloat32,
    }

    @classmethod
    def get(cls, index: int, datatype: str = 'uint16', *, is_input: bool = False,
            ratio=1, offset=0, decimals=None, word_order=None) -> Reader:
        """ word_order is accepted only by 32-bit datatypes """
        kwargs = dict(ratio=ratio, offset=offset, decimals=decimals)
        reader_cls = cls.reader_classes.get(datatype)
        if reader_cls is None:
            logger.warning(f'Unknown datatype "{datatype}" in ReaderFactory index={index}')
            return Reader(index, is_input, **kwargs)
        if word_order is not None:
            if not issubclass(reader_cls, Reader32):
                raise ValueError(f'Datatype "{datatype}" does not support word_order')
            kwargs['word_order'] = word_order
        return reader_cls(index, is_input, **kwargs)
