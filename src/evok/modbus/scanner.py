#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging

from tmodbus import (
    AsyncModbusClient,
    AsyncTcpTransport,
    AsyncSmartTransport
)

from .. import devents
from ..devices import MODBUS_SLAVE, Devices, to_bool
from ..errors import describe_error, root_cause
from .builder import IOParser
from .cache import ModbusCacheMap
from .client import Client

logger = logging.getLogger(__name__)


def _error_kind(error: BaseException | None) -> type | None:
    """ The type of the root cause of the error, the errors around it differ by the retries: the first failure
        of a unit is a RequestRetryFailedError of tmodbus, the next ones without the retries are not
    """
    return None if error is None else type(root_cause(error))


class ModbusScanner:
    """ A Modbus unit, its devices are created after its first scan

        With scan_enabled the unit is scanned periodically, without it the values
        of its devices are changed only by the writes of Evok.
    """

    INITIAL_SCAN_INTERVAL = 2       # [s] the first retry of the first scan, it is slowed down as a failing unit
    MAX_SCAN_INTERVAL = 16          # [s] the slowed down scan of a failing unit

    def __init__(self, transport: AsyncSmartTransport,
                 circuit, scan_freq, scan_enabled, hw_definition,
                 unit_id: int):
        if not isinstance(scan_freq, (int, float)) or isinstance(scan_freq, bool) or not scan_freq > 0:
            raise ValueError(f"scan_frequency must be a positive number, not '{scan_freq}'")
        if not isinstance(scan_enabled, bool):
            raise ValueError(f"scan_enabled must be true or false, not '{scan_enabled}'")
        is_tcp = isinstance(transport.base_transport, AsyncTcpTransport)
        # 0 is the broadcast of RTU without a response, a TCP gateway uses also 0 and 248..255
        min_id, max_id = (0, 255) if is_tcp else (1, 247)
        if not isinstance(unit_id, int) or isinstance(unit_id, bool) or not min_id <= unit_id <= max_id:
            raise ValueError(f"slave-id must be an integer {min_id}..{max_id}, not '{unit_id}'")
        self.alias = ""
        self.devtype = MODBUS_SLAVE
        self.circuit: str | None = circuit
        self.modbus_address = unit_id
        self.modbus_type = 'TCP' if is_tcp else 'RTU'
        self.modbus_spec = transport.base_transport.host if is_tcp else \
            transport.base_transport.port
        self.name = f"{self.modbus_type}:{self.modbus_spec}:{self.modbus_address}"
        self.scan_interval = 1.0 / scan_freq

        self.scan_task: asyncio.Task | None = None
        self.scan_enabled = scan_enabled
        self.populated = False      # the devices are created once, also when the scan is started again
        self.logged_scan_error: str | None = None  # repr of an unexpected error, logged once until a scan succeeds

        mb_client = AsyncModbusClient(transport,
                                      unit_id=unit_id,
                                      word_order="little")

        self.cache = ModbusCacheMap(hw_definition.get('modbus_register_blocks', []),
                                    mb_client)

        # the unit is known by its name in the configuration, the transport and the address tell where it is
        self.client = Client(f"'{circuit}' ({self.name})", mb_client, self.cache)
        self.client.periodic_scan = scan_enabled
        self.parser = IOParser(self.client, hw_definition.get('modbus_features', []), circuit)

    def start_scanning(self):
        """ Create the devices after the first scan, then scan periodically with scan_enabled """
        if self.scan_task is None or self.scan_task.done():
            self.scan_task = asyncio.create_task(self._scan_loop())
            self.scan_task.add_done_callback(self._log_scan_task_error)

    async def stop_scanning(self):
        """ Cancel the scan and wait for it, it does not use the bus after the return """
        task, self.scan_task = self.scan_task, None
        if task is not None:
            task.cancel()
            # an error of the task is logged by its done callback, wait() does not raise it
            await asyncio.wait([task])

    async def set(self, scan_enabled=None, alias=None):
        """ Enable or disable the periodic scan, set the alias

            scan_enabled true also starts again a scan stopped by an unexpected error. The first scan,
            which creates the devices, runs also with scan_enabled false.
        """
        if scan_enabled is not None:
            scan_enabled = to_bool(scan_enabled)
        # an invalid alias raises ValueError before the scan is changed
        if alias is not None:
            Devices.set_alias(alias, self)
        if scan_enabled is not None:
            self.scan_enabled = self.client.periodic_scan = scan_enabled
            if scan_enabled:
                self.start_scanning()
            elif self.populated:
                # the task waiting for the first scan ends after creating the devices
                await self.stop_scanning()
        if scan_enabled is not None or alias is not None:
            # the clients of WebSocket get the new state
            devents.status(self)

    def _log_scan_task_error(self, task: asyncio.Task):
        """ An unexpected error stops the scan of the unit, it would not be logged by the task """
        if not task.cancelled() and task.exception() is not None:
            logger.error(f"{self.name}: Scan of device '{self.circuit}' stopped", exc_info=task.exception())

    async def _scan_unit(self) -> bool:
        try:
            res = await self.client.do_scan()
        except Exception as E:
            # reported by full(), the communication errors are set by the cache
            self.cache.scan_error = E
            self.client.send_comm_change()
            # the error repeats on every scan, do not flood the log
            if repr(E) != self.logged_scan_error:
                self.logged_scan_error = repr(E)
                logger.exception(f"{self.name}: Error while scanning, the same error is not logged "
                                 f"until a scan succeeds: {E}")
            return False
        if res:
            self.logged_scan_error = None
        return res

    def _set_failing(self, failing: bool):
        """ A unit which does not respond is probed by one short request, the other units of the bus wait less """
        set_failing = getattr(getattr(self.client.mb_client, 'transport', None), 'set_failing', None)
        if set_failing is not None:
            set_failing(self.modbus_address, failing)

    async def _scan_loop(self):
        """ Wait for the connected unit, a communication error is retried, it is logged once.
            Create its devices, then scan it periodically with scan_enabled.
            A started again scan does not create the devices again.

            A missing unit is retried slower and slower up to MAX_SCAN_INTERVAL, every 2 s it took
            a third to a half of a shared RTU bus. A lost and a restored communication is sent
            as an event of the unit.
        """
        if not self.populated:
            logged_error = None
            interval = self.INITIAL_SCAN_INTERVAL
            while not await self.cache.do_scan(initial=True):
                self._set_failing(True)
                error = self.cache.scan_error
                if logged_error is None:
                    devents.status(self)
                if _error_kind(error) != _error_kind(logged_error):
                    logger.warning(f"Waiting for device '{self.circuit}': {describe_error(error)}")
                    logged_error = error
                await asyncio.sleep(interval)
                interval = min(interval * 2, self.MAX_SCAN_INTERVAL)
            self._set_failing(False)
            if logged_error is not None:
                logger.info(f"Device '{self.circuit}' is connected")
                devents.status(self)

            self.parser.populate()
            self.populated = True
            # the values of the devices from the first scan, without scan_enabled they were null until a change
            await self.client.check_devices()
        if not self.scan_enabled:
            return

        loop = asyncio.get_running_loop()
        interval = self.scan_interval
        err = False
        next_scan = loop.time()
        while True:
            # the interval is the period of the scans, not the pause after a scan;
            # a scan longer than the interval is followed by the next one, the missed ones are not caught up
            next_scan = max(next_scan + interval, loop.time())
            await asyncio.sleep(next_scan - loop.time())
            if await self._scan_unit():
                if err:
                    err = False
                    self._set_failing(False)
                    logger.info(f"Communication with device is back: '{self.circuit}'")
                    devents.status(self)
                interval = self.scan_interval
            else:
                if not err:
                    err = True
                    self._set_failing(True)
                    logger.warning(f"Slowing down device: '{self.circuit}': {describe_error(self.cache.scan_error)}")
                    devents.status(self)
                # exponential growth interval with limitation [s]
                interval = min(interval * 2, max(self.MAX_SCAN_INTERVAL, self.scan_interval))

    def full(self):
        scan_error = self.cache.scan_error
        ret = {'dev': 'modbus_slave',
               'circuit': self.circuit,
               'slave_id': self.modbus_address,
               'modbus_type': self.modbus_type,
               'modbus_spec': self.modbus_spec,
               'scan_interval': self.scan_interval,
               'scan_enabled': self.scan_enabled,
               'last_comm': self.client.last_comm(),
               'scan_error': describe_error(scan_error) if scan_error is not None else None,
               'comm': self.client.comm(),
               }
        if self.alias != '':
            ret['alias'] = self.alias

        return ret
