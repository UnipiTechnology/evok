#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 13:40:31 2026

@author: bokula
"""

from tmodbus import (
    AsyncModbusClient
)

from .cache import ModbusCacheMap
from ..devices import devents
from ..log import logger

class Client:

    def __init__(self, name: str,
                 mb_client: AsyncModbusClient,
                 cache: ModbusCacheMap):
        self.name = name
        self.cache = cache
        self.mb_client = mb_client
        self.eventable_devices = []

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
