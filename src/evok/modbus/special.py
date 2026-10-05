#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio

from copy import copy

from ..devices import OWPOWER, WATCHDOG, NV_SAVE
from ..log import logger
from .base import IODevice
from .client import Client, AccessorU16


class OwPower(IODevice):

    devtype = OWPOWER

    def __init__(self, circuit, client: Client, coil, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.value = 0

    def full(self):
        ret = {'dev': 'owpower', 'circuit': self.circuit, 'value': self.value}
        self._with_alias(ret)
        return ret

    async def set(self, value=None, alias=None):
        """ Sets new on/off status.
        """
        self.set_alias(alias)
        if value is not None:
            value = bool(int(value))
            self.value = value
            await self.client.mb_client.write_single_coil(self.coil, value)
        return self.full()


class NvSave(IODevice):

    devtype = NV_SAVE

    def __init__(self, circuit, client: Client, coil, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.value = 0

    def full(self):
        ret = {'dev': 'nv_save', 'circuit': self.circuit, 'value': self.value}
        self._with_alias(ret)
        return ret

    async def set(self, value=None, alias=None):
        """ Schedule writing of startup data in firmware if value=1,
            the value is reported only in the response of this call
        """
        self.set_alias(alias)
        if value is not None and int(value):
            await self.client.mb_client.write_single_coil(self.coil, 1)
            await asyncio.sleep(0.2)
            return {**self.full(), 'value': 1}
        return self.full()


class Watchdog(IODevice):

    devtype = WATCHDOG

    def __init__(self, circuit, client: Client, post, reg, timeout_reg, nv_save_coil=-1, reset_coil=-1,
                 wd_reset_ro_coil=-1, major_group=0):
        super().__init__(circuit, client, major_group)
        self.nvsavvalue = 0
        self.resetvalue = 0
        self.nv_save_coil = nv_save_coil
        self.reset_coil = reset_coil
        self.wd_reset_ro_coil = wd_reset_ro_coil
        self.wdwasresetvalue = 0
        self.accessor = AccessorU16(reg)
        self.accessor_timeout = AccessorU16(timeout_reg)

        self.value = None
        self.timeout = None
        self.was_wd_boot_value = None

    def full(self):
        ret = {'dev': 'wd',
               'circuit': self.circuit,
               'value': self.value,
               'timeout': self.timeout,
               'was_wd_reset': self.was_wd_boot_value,
               'nv_save': self.nvsavvalue,
               }
        self._with_alias(ret)
        return ret

    async def check_new_data(self):
        old_value = copy(self.value)
        self.value = self.accessor.read(self.client) & 0x03  # Only the two lowest bits contains watchdog status
        self.timeout = self.accessor_timeout.read(self.client)
        self.was_wd_boot_value = 1 if self.value & 0b10 else 0
        return old_value != self.value

    async def set(self, value=None, timeout=None, reset=None, nv_save=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        self.set_alias(alias)

        if value is not None:
            value = int(value)
            await self.accessor.write(self.client, 1 if value else 0)

        if timeout is not None:
            timeout = min(int(timeout), 65535)
            await self.accessor_timeout.write(self.client, timeout)

        if self.nv_save_coil >= 0 and nv_save is not None and nv_save != self.nvsavvalue:
            if nv_save != 0:
                self.nvsavvalue = 1
            else:
                self.nvsavvalue = 0
            await self.client.mb_client.write_single_coil(self.nv_save_coil, 1)

        if self.reset_coil >= 0 and reset is not None:
            if reset != 0:
                self.nvsavvalue = 0
                await self.client.mb_client.write_single_coil(self.reset_coil, 1)
                logger.info("Performed reset of board %s" % self.circuit)

        return self.full()
