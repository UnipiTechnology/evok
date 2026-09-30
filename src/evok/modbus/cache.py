#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Sep 24 15:10:48 2026

@author: Miroslav Ondra
"""

import time

from dataclasses import dataclass, field
from tmodbus import AsyncModbusClient
from tmodbus.exceptions import ModbusConnectionError


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
        return self.address <= address and self.address + self.count >= address + count

    def update(self, values, address=None):
        offset = address - self.address if address is not None else 0
        if offset < 0:
            return
        for i in range(0, min(len(values), len(self.values) - offset)):
            self.values[i + offset] = values[i]

    def clear_counter(self):
        self.f_counter = 0

    def tick_counter(self):
        self.f_counter = self.f_divider - 1 if self.f_counter == 0 else \
            self.f_counter - 1


class ModbusCacheMap(object):

    def __init__(self, modbus_reg_map, modbus_client):
        self.modbus_client: AsyncModbusClient = modbus_client
        self.last_comm_time = 0
        self.groups = [RegisterGroup(address=mg["start_reg"],
                                     count=mg["count"],
                                     f_divider=mg["frequency"])
                       for mg in modbus_reg_map
                       if mg.get("type", "holding") == "holding"]
        self.igroups = [RegisterGroup(address=mg["start_reg"],
                                      count=mg["count"],
                                      f_divider=mg["frequency"])
                        for mg in modbus_reg_map
                        if mg.get("type", "holding") == "input"]

    async def do_scan(self, initial: bool = False) -> bool:
        if initial:
            [g.clear_counter() for g in self.groups]
            [g.clear_counter() for g in self.igroups]

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

    async def _do_scan_groups(self, groups: list[RegisterGroup], func) -> bool:
        try:
            for group in groups:
                if (group.f_counter == 0):
                    vals = await func(group.address, quantity=group.count)
                    group.update(vals)
                group.tick_counter()

        except (ModbusConnectionError, TimeoutError):
            return False

        return True


def raise_if_null(data, index):
    if index >= len(data) or data[index] is None:
        raise ENoCacheRegister(f"No cached value of register '{index}'")
    return data[index]
