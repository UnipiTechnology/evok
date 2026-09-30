#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from copy import copy

from ..devices import OWPOWER, WATCHDOG, NV_SAVE, Devices
from ..log import logger
from .client import Client


class OwPower(object):
    def __init__(self, circuit, client: Client, coil, major_group=0):
        self.alias = ""
        self.devtype = OWPOWER
        self.circuit = circuit
        self.client = client
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
            await self.client.mb_client.write_single_coil(self.coil, 1 if value else 0)
        return self.full()

    def get(self):
        return self.full()


class NvSave(object):
    def __init__(self, circuit, client: Client, coil, major_group=0):
        self.alias = ""
        self.devtype = NV_SAVE
        self.circuit = circuit
        self.client = client
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
            await self.client.mb_client.write_single_coil(self.coil, 1 if value else 0)
        return self.full()

    def get(self):
        return self.full()


class Watchdog(object):
    def __init__(self, circuit, client: Client, post, reg, timeout_reg, nv_save_coil=-1, reset_coil=-1, wd_reset_ro_coil=-1,
                 major_group=0, legacy_mode=True):
        self.alias = ""
        self.devtype = WATCHDOG
        self.circuit = circuit
        self.client = client
        self.major_group = major_group
        self.legacy_mode = legacy_mode
        self.timeoutvalue = lambda: self.client.read_u16(self.toreg)
        self.regvalue = lambda: self.client.read_u16(self.valreg)
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
        self.timeout = self.timeoutvalue()
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
        await self.client.mb_client.write_single_register(self.valreg, 1 if value else 0)
        return 1 if value else 0

    async def set(self, value=None, timeout=None, reset=None, nv_save=None, alias=None):
        """ Sets new on/off status. Disable pending timeouts
        """
        if alias is not None:
            Devices.set_alias(alias, self)

        if value is not None:
            value = int(value)
            await self.client.mb_client.write_single_register(self.valreg, 1 if value else 0)

        if timeout is not None:
            timeout = int(timeout)
            if timeout > 65535:
                timeout = 65535
            await self.client.mb_client.write_single_register(self.toreg, timeout)

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
