#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:58:27 2026

@author: bokula
"""

import asyncio
import time

from tmodbus import (
    AsyncModbusClient,
    AsyncTcpTransport,
    AsyncSmartTransport
)
from typing import Union


from ..devices import MODBUS_SLAVE
from ..log import logger
from .builder import IOParser
from .cache import ModbusCacheMap
from .client import Client


class ModbusScanner:

    INITIAL_SCAN_INTERVAL = 2

    def __init__(self, transport: AsyncSmartTransport,
                 circuit, scan_freq, scan_enabled, hw_definition,
                 unit_id: int):
        self.alias = ""
        self.devtype = MODBUS_SLAVE
        self.circuit: Union[None, str] = circuit
        self.modbus_address = unit_id
        is_tcp = isinstance(transport.base_transport, AsyncTcpTransport)
        self.modbus_type = 'TCP' if is_tcp else 'RTU'
        self.modbus_spec = transport.base_transport.host if is_tcp else \
            transport.base_transport.port
        self.name = f"{self.modbus_type}:{self.modbus_spec}:{self.modbus_address}"
        self.scan_interval = 1.0 / scan_freq if scan_freq != 0 else 0.0001

        # self.boards = list()
        self.scan_task: Union[None, asyncio.Task] = None
        self.scan_enabled = scan_enabled
        self.versions = []

        mb_client = AsyncModbusClient(transport,
                                      unit_id=unit_id,
                                      word_order="little")

        self.cache = ModbusCacheMap(hw_definition.get('modbus_register_blocks', []),
                                    mb_client)

        self.client = Client(self.name, mb_client, self.cache)
        self.parser = IOParser(self.client, hw_definition.get('modbus_features', []), circuit)

    def start_scanning(self):
        if self.scan_task is None or self.scan_task.done():
            self.scan_task = asyncio.create_task(self._scan_loop())

    def stop_scanning(self):
        if self.scan_task is not None:
            self.scan_task.cancel()
            self.scan_task = None

    async def _scan_unit(self) -> bool:
        try:
            return await self.client.do_scan()
        except Exception as E:
            logger.exception(f"{self.name}: Error while scanning: {E}")
            return False

    async def _scan_loop(self):
        '''
            Wait for connected device, a communication error is retried, it is logged once.
            Create IO devices.
        '''
        logged_error = None
        while not await self.cache.do_scan(initial=True):
            error = self.cache.scan_error
            if repr(error) != repr(logged_error):
                logger.warning(f"Waiting for device '{self.circuit}': {error!r}")
                logged_error = error
            await asyncio.sleep(self.INITIAL_SCAN_INTERVAL)
        if logged_error is not None:
            logger.info(f"Device '{self.circuit}' is connected")

        self.parser.populate()

        interval = self.scan_interval
        err = False
        while True:
            await asyncio.sleep(interval)
            if await self._scan_unit():
                if err:
                    err = False
                    logger.info(f"Communication with device is back: '{self.circuit}'")
                interval = self.scan_interval
            else:
                if not err:
                    err = True
                    # other errors are logged by _scan_unit()
                    cause = f": {self.cache.scan_error!r}" if self.cache.scan_error is not None else ""
                    logger.warning(f"Slowing down device: '{self.circuit}'{cause}")
                # exponential growth interval with limitation [s]
                interval = min(interval * 2, max(120, self.scan_interval))

    def get(self):
        return self.full()

    def full(self):
        ret = {'dev': 'modbus_slave',
               'circuit': self.circuit,
               'slave_id': self.modbus_address,
               'modbus_type': self.modbus_type,
               'modbus_spec': self.modbus_spec,
               'scan_interval': self.scan_interval,
               'last_comm': time.time() - self.cache.last_comm_time,
               }
        if self.alias != '':
            ret['alias'] = self.alias

        return ret
