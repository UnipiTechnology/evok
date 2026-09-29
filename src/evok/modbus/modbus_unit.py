#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Sep 29 09:58:27 2026

@author: bokula
"""

import asyncio
import logging
import traceback
import time

from tmodbus import (
    AsyncModbusClient,
    AsyncTcpTransport,
    AsyncSmartTransport
)
from tmodbus.exceptions import TModbusError, ModbusConnectionError
from typing import Union


from ..devices import MODBUS_SLAVE
from ..log import logger
from .builder import Board
from .cache import ModbusCacheMap, ENoCacheRegister

import subprocess


class ModbusSlave:

    def __init__(self, transport: AsyncSmartTransport,
                 circuit, evok_config, scan_freq, scan_enabled, hw_definition: dict, slave_id=1,
                 major_group=1, device_model='unspecified'):
        self.alias = ""
        self.devtype = MODBUS_SLAVE
        self.modbus_cache_map = None
        self.eventable_devices = list()
        self.hw_definition = hw_definition
        self.modbus_address = slave_id
        self.device_model = device_model
        self.evok_config = evok_config
        self.scan_task: Union[None, asyncio.Task] = None
        self.major_group = major_group
        if scan_freq == 0:
            self.scan_interval = 0.0001
            # scan_interval cannot be zero!! (slowing down device)
        else:
            self.scan_interval = 1.0 / scan_freq
        self.scan_enabled = scan_enabled
        self.versions = []
        self.logfile = evok_config.logging.get("file", "./evok.log")
        self.client: AsyncModbusClient = AsyncModbusClient(transport, unit_id=slave_id, word_order="little")
        self.circuit: Union[None, str] = circuit
        if isinstance(transport.base_transport, AsyncTcpTransport):
            self.modbus_type = 'TCP'
            self.modbus_spec = transport.base_transport.host
        else:
            self.modbus_type = 'RTU'
            self.modbus_spec = transport.base_transport.port

    def get(self):
        return self.full()

    def switch_to_async(self):
        self._rb_task = asyncio.create_task(self.readboards())

    async def set(self, print_log=None):
        if print_log is not None and print_log != 0:
            log_tail = subprocess.check_output(["tail", "-n 255", self.logfile])
            return log_tail
        else:
            return ""

    async def readboards(self):
        logger.info(f"Initial reading the Modbus board on Modbus address {self.modbus_address}\t({self.circuit})")
        try:
            board = Board(self.evok_config, self.circuit, self.modbus_address, self, self.hw_definition)
            await board.parse_definition()
        except (ModbusConnectionError, TimeoutError) as E:
            logger.error(f"No board detected on Modbus {self.modbus_address}\t({type(E).__name__}:{E})")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
        except Exception as E:
            logger.exception(str(E))
            pass

    def start_scanning(self):
        if self.scan_task is None or self.scan_task.done():
            self.scan_task = asyncio.create_task(self.scan_loop())

    async def scan_loop(self):
        interval = self.scan_interval
        err = False
        while True:
            await asyncio.sleep(interval)
            if await self.scan_boards():
                if err:
                    err = False
                    logger.info(f"Communication with device is back: '{self.circuit}'")
                interval = self.scan_interval
            else:
                if not err:
                    err = True
                    logger.warning(f"Slowing down device: '{self.circuit}'")
                #exponential growth interval with limitation [s]
                interval = min(interval * 2, max(120, self.scan_interval))

    def stop_scanning(self):
        if self.scan_task is not None:
            self.scan_task.cancel()
            self.scan_task = None

    async def scan_boards(self) -> bool:
        try:
            return self.modbus_cache_map is None \
                or await self.modbus_cache_map.do_scan()
        except Exception as E:
            logger.exception(f"{self.circuit}: Error while scanning: {E}")
            return False

    def full(self):
        ret = {'dev': 'modbus_slave',
               'circuit': self.circuit,
               'last_comm': 0x7fffffff,
               'slave_id': self.modbus_address,
               'modbus_type': self.modbus_type,
               'modbus_spec': self.modbus_spec,
               'scan_interval': self.scan_interval,
               }
        if self.alias != '':
            ret['alias'] = self.alias
        if self.modbus_cache_map is not None:
            ret['last_comm'] = time.time() - self.modbus_cache_map.last_comm_time

        # TODO: zkontrolovat, jestli existruji v 'self.client'
        'modbus_server'
        'modbus_port'
        'uart_circuit'
        'uart_port'

        if self.alias != '':
            ret['alias'] = self.alias
        if self.modbus_cache_map is not None:
            ret['last_comm'] = time.time() - self.modbus_cache_map.last_comm_time
        return ret


