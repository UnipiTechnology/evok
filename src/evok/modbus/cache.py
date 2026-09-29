#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Sep 24 15:10:48 2026

@author: Miroslav Ondra
"""

import asyncio
import time

from copy import deepcopy
from dataclasses import dataclass, field
from tmodbus import AsyncModbusClient
from tmodbus.exceptions import TModbusError, ModbusConnectionError

from ..devices import devents
from ..log import logger


class ENoCacheRegister(Exception):
    pass


@dataclass
class RegisterGroup:
    address: int
    count: int
    f_divider: int = 1
    f_counter: int = 0
    values: list[int] = field(init=False)

    def __post_init__(self):
       self.values = [None] * self.count
        
    def is_member(self, address: int, count: int = 1) -> bool:
        return self.address <= address and self.address+self.count >= address + count

    def update(self, values, address = None):
        offset = address - self.address if address is not None else 0
        if offset < 0:
            return
        for i in range(0, min(len(values), len(self.values)-offset)):
            self.values[i+offset] = values[i]

    def clear_counter(self): 
        self.f_counter = 0;

    def tick_counter(self): 
        self.f_counter = self.f_divider - 1 if self.f_counter == 0 else \
                         self.f_counter - 1


class XModbusCacheMap(object):
    
    def __init__(self, modbus_reg_map, modbus_client):
        self.modbus_client: AsyncModbusClient = modbus_client
        self.last_comm_time = 0
        self.groups = [ RegisterGroup(address=mg["start_reg"],
                                      count=mg["count"],
                                      f_divider=mg["frequency"]) \
                        for mg in modbus_reg_map \
                            if mg.get("type","holding")=="holding"]
        self.igroups = [ RegisterGroup(address=mg["start_reg"],
                                      count=mg["count"],
                                      f_divider=mg["frequency"]) \
                        for mg in modbus_reg_map \
                            if mg.get("type","holding")=="input"]


    async def do_scan(self, initial:bool=False) -> bool:
        if initial:
            [ g.clear_counter() for g in self.groups ]
            [ g.clear_counter() for g in self.igroups ]

        res = await self._do_scan_groups(self.groups, self.modbus_client.read_holding_registers) and \
              await self._do_scan_groups(self.igroups, self.modbus_client.read_input_registers)
        if res:
            self.last_comm_time = time.time()
        return res

    def _find_group(self, address: int, is_input: bool) -> RegisterGroup:
        for group in (self.igroups if is_input else self.groups):
            if group.is_member(address):
                return group
        raise ValueError(f"get_reg_group: Unknown register {address}!")

    def get_register(self, count, index, is_input=False):
        group = self._find_group(index, is_input)
        offset = index - group.address
        return [raise_if_null(group.values, offset + i) for i in range(count)]

    def set_register(self, index, values, is_input=False):
        """ Update cached registers after a successful write """
        self._find_group(index, is_input).update(values, index)

    async def get_register_async(self, count, index, is_input=False):
        group = self._find_group(index, is_input)
        # ^^ raise exception if index not in cache map!
        if is_input:
            vals = await self.modbus_client.read_input_registers(index, quantity=count)
        else:
            vals = await self.modbus_client.read_holding_registers(index, quantity=count)
        group.update(vals, index)
        return vals

    async def _do_scan_groups(self, groups:list[RegisterGroup], func) -> bool:
        try:
            for group in groups:
                if (group.f_counter == 0):
                    vals = await func(group.address, quantity=group.count)
                    group.update(vals)
                group.tick_counter()

        except ModbusConnectionError:
            return False

        return True



def raise_if_null(data, index):
    if index >= len(data) or data[index] is None:
        raise ENoCacheRegister(f"No cached value of register '{index}'")
    return data[index]


class ModbusCacheMap(object):
    def __init__(self, modbus_reg_map, modbus_slave):
        self.last_comm_time = 0
        self.modbus_reg_map = deepcopy(modbus_reg_map)
        self.modbus_slave = modbus_slave
        self.sem = asyncio.Semaphore(1)
        self.frequency = {}
        self.initial_read = True
        for m_reg_group in self.modbus_reg_map:
            self.frequency[m_reg_group['start_reg']] = 10000001  # frequency less than 1/10 million are not read on start
            m_reg_group['values'] = [None for i in range(m_reg_group['count'])]

    def __get_reg_group(self, index: int, is_input: bool):
        group = None
        _index = None
        for m_reg_group in self.modbus_reg_map:
            group_is_input = m_reg_group.get('type', None) == 'input'
            if group_is_input is is_input and \
                    ((m_reg_group['start_reg']) <= index < (m_reg_group['count'] + m_reg_group['start_reg'])):
                group = m_reg_group['values']
                _index = index - m_reg_group['start_reg']
                # print(f"index: '{index}' cont: '{count}'\tfind in: '{m_reg_group}'")
                break
        if group is None:
            raise ValueError(f"get_reg_group: Unknown register {index}!")
        return group, _index

    def get_register(self, count, index, is_input=False):
        try:
            group, _index = self.__get_reg_group(index=index, is_input=is_input)
            return [raise_if_null(group, _index + i) for i in range(count)]
        except (IndexError, KeyError) as E:
            raise ValueError(f"get_register: get register {index} error: {E}")

    def set_register(self, index, values, is_input=False):
        """ Update cached registers after a successful write """
        group, group_index = self.__get_reg_group(index=index, is_input=is_input)
        for i, value in enumerate(values):
            group[group_index + i] = value

    async def get_register_async(self, count, index, is_input=False):
        group, group_index = self.__get_reg_group(index=index, is_input=is_input)
        # ^^ raise exception if index not in cache map!

        # read values from modbus
        if is_input:
            val = await self.modbus_slave.client\
                        .read_input_registers(index, quantity=count)
        else:
            val = await self.modbus_slave.client\
                        .read_holding_registers(index, quantity=count)

        # update cache map
        for i in range(len(val)):
            group[group_index + i] = val[i]
        return val

    async def do_scan(self, initial=False) -> bool:
        if initial:
            await self.sem.acquire()
        changeset = []

        scanned = False
        for m_reg_group in self.modbus_reg_map:
            m_reg_group: dict
            if (self.frequency[m_reg_group['start_reg']] >= m_reg_group['frequency']) or \
               (self.frequency[m_reg_group['start_reg']] == 0):    # only read once for every [frequency] cycles
                vals = None
                try:
                    # read values from modbus
                    if 'type' in m_reg_group and m_reg_group['type'] == 'input':
                        vals = await self.modbus_slave.client \
                                     .read_input_registers( \
                                         m_reg_group['start_reg'],                          
                                         quantity=m_reg_group['count'])
                    else:
                        vals = await self.modbus_slave.client \
                                     .read_holding_registers( \
                                         m_reg_group['start_reg'],
                                         quantity=m_reg_group['count'])

                    #if vals is not None and len(vals.registers) == m_reg_group['count']:
                    #update modbus cache
                    m_reg_group['values'] = vals

                    # call force update callbacks in registered devices and check differences
                    for device in self.modbus_slave.eventable_devices:
                        try:
                            if await device.check_new_data() is True:
                                changeset.append(device)
                        except Exception as E:
                            m = (f"Error while checking new data in device '{device.devtype}"
                                 f"_{device.circuit}': {E}")
                            logger.exception(m)

                    # reset communication flags
                    self.last_comm_time = time.time()
                    scanned = True

                except (TModbusError, TimeoutError) as E:
                    logger.error(E)
                    pass # ToDo: logging

                finally:
                    self.frequency[m_reg_group['start_reg']] = 1
            else:
                self.frequency[m_reg_group['start_reg']] += 1
        if len(changeset) > 0:
            proxy = Proxy(set(changeset))
            # print(f"changeset: {changeset}")
            devents.status(proxy)
        if initial:
            self.sem.release()
        return scanned

class Proxy(object):
    def __init__(self, changeset):
        self.changeset = changeset

    def full(self):
        self.result = [c.full() for c in self.changeset]
        self.full = self.fullcache
        return self.result

    def fullcache(self):
        return self.result
            