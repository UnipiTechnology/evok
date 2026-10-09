#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from ..devices import Devices
from .client import Client


class IODevice:
    """ Base class of the IO devices on a Modbus unit

        Subclasses set `devtype` and implement full() and set()
    """

    devtype = None

    def __init__(self, circuit, client: Client, major_group=0):
        self.alias = ""
        self.circuit = circuit
        self.client = client
        self.major_group = major_group

    def full(self) -> dict:
        """ Return the complete state of the device """
        raise NotImplementedError

    def get(self):
        return self.full()

    async def set(self, alias=None, **kwargs) -> None:
        """ Change the device settings, the caller reads the new state by full() """
        raise NotImplementedError

    def set_alias(self, alias):
        """ Set the alias if it is given """
        if alias is not None:
            Devices.set_alias(alias, self)

    def _with_alias(self, ret: dict) -> dict:
        """ Add the alias to a state dict if the device has one """
        if self.alias != '':
            ret['alias'] = self.alias
        return ret


async def set_devices(assignments: list[tuple], states: dict | None = None) -> list[dict]:
    """ Set the devices by the params of assignments [(device, kw)], return their states in the same order

        The devices of a Modbus unit are set under the lock of the unit by Client.change(), the unit
        is read and the states follow the writes. The units are set one after another, in the order
        of their first assignment, the other devices one by one. A change of only the alias does not
        write the unit, it is set also on an unavailable unit.

        On an error, states (index of the assignment: state) has the states of the assignments done
        before it, also of its unit, the units after it are not set.

        set() of a device on a Modbus unit runs under the lock of its unit, it must not call set_devices()
        or Client.change() of the same unit: the lock is not reentrant, it would wait for itself forever.
    """
    states = {} if states is None else states
    units: dict = {}
    for index, (device, kw) in enumerate(assignments):
        unit = device.client if isinstance(device, IODevice) else device
        units.setdefault(unit, []).append((index, device, kw))

    for unit, items in units.items():
        done = []

        async def operation():
            for index, device, kw in items:
                await device.set(**kw)
                done.append((index, device))
        try:
            if isinstance(unit, Client):
                writes = any(set(kw) - {'alias'} for _, _, kw in items)
                await unit.change(operation, check_available=writes, read=writes)
            else:
                await operation()
        finally:
            for index, device in done:
                states[index] = device.full()
    return [states[index] for index in range(len(assignments))]
