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
