#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import time

from dataclasses import dataclass, field
from tmodbus import AsyncModbusClient
from tmodbus.exceptions import TModbusError


class ENoCacheRegister(Exception):
    pass


@dataclass
class RegisterGroup:
    address: int
    count: int
    f_divider: int = 1
    f_counter: int = 0
    values: list[int | None] = field(init=False)     # None before the first read

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


def _make_group(block: dict) -> RegisterGroup:
    """ A register block of a hardware definition, raise ValueError if it is invalid """
    def positive_int(name, minimum):
        value = block.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"Register block {block}: '{name}' must be an integer >= {minimum}")
        return value

    if block.get("type", "holding") not in ("holding", "input"):
        raise ValueError(f"Register block {block}: unknown type '{block['type']}', use 'holding' or 'input'")
    return RegisterGroup(address=positive_int("start_reg", 0),
                         count=positive_int("count", 1),
                         f_divider=positive_int("frequency", 1))


class ModbusCacheMap:

    def __init__(self, modbus_reg_map, modbus_client):
        self.modbus_client: AsyncModbusClient = modbus_client
        self.last_comm_time: float | None = None    # None before the first successful scan
        # the error of the last scan, None after a successful one
        self.scan_error: Exception | None = None
        self.groups = []
        self.igroups = []
        for block in modbus_reg_map:
            group = _make_group(block)
            groups = self.igroups if block.get("type") == "input" else self.groups
            # a register is read from the first group, the copy in an overlapping one would not be used
            for other in groups:
                if group.address < other.address + other.count and other.address < group.address + group.count:
                    raise ValueError(f"Register block {block} overlaps the block of registers "
                                     f"{other.address}..{other.address + other.count - 1}")
            groups.append(group)

    async def do_scan(self, initial: bool = False) -> bool:
        if initial:
            for group in self.groups + self.igroups:
                group.clear_counter()

        read = 0
        for groups, func in ((self.groups, self.modbus_client.read_holding_registers),
                             (self.igroups, self.modbus_client.read_input_registers)):
            count = await self._do_scan_groups(groups, func)
            if count is None:
                return False
            read += count
        # the counters are ticked after the whole scan, a failed scan is repeated with the same groups,
        # the slow groups keep their phase
        for group in self.groups + self.igroups:
            group.tick_counter()
        # a scan without a read, e.g. of a unit without register blocks, is not a communication
        if read > 0:
            self.last_comm_time = time.time()
        self.scan_error = None
        return True

    def _find_group(self, address: int, is_input: bool) -> RegisterGroup:
        for group in (self.igroups if is_input else self.groups):
            if group.is_member(address):
                return group
        raise ValueError(f"get_reg_group: Unknown register {address}!")

    def get_register(self, index, count=1, is_input=False):
        group = self._find_group(index, is_input)
        offset = index - group.address
        values = group.values[offset:offset + count]
        for i in range(count):
            if i >= len(values) or values[i] is None:
                raise ENoCacheRegister(f"No cached value of register {index + i}")
        return values

    def set_register(self, index, values, is_input=False):
        """ Update cached registers after a successful write """
        self._find_group(index, is_input).update(values, index)

    async def get_register_async(self, index, count=1, is_input=False):
        group = self._find_group(index, is_input)
        # ^^ raise exception if index not in cache map!
        if is_input:
            vals = await self.modbus_client.read_input_registers(index, quantity=count)
        else:
            vals = await self.modbus_client.read_holding_registers(index, quantity=count)
        group.update(vals, index)
        return vals

    async def _do_scan_groups(self, groups: list[RegisterGroup], func) -> int | None:
        """ The number of the read groups, None after a communication error """
        read = 0
        try:
            for group in groups:
                if group.f_counter == 0:
                    vals = await func(group.address, quantity=group.count)
                    group.update(vals)
                    read += 1

        except (TModbusError, TimeoutError) as E:
            # also the retries of the transport (RequestRetryFailedError), a noise on RS485 (CRCError)
            # and the exception responses of the unit, e.g. an address out of its registers
            self.scan_error = E
            return None

        return read
