#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import time

from tmodbus import AsyncSmartTransport


class BusTransport(AsyncSmartTransport):
    """ The transport of a Modbus bus, shared by its units

        A unit which does not respond (its scan failed) is probed by one request with probe_timeout,
        without the retries. Every scan of a missing unit locked the bus for (retries + 1) * timeout
        and the other units of the bus waited, e.g. 1 s with the defaults.

        The probe uses the lock of the bus and the reconnection of AsyncSmartTransport (tmodbus 0.6.2),
        a cancelled request is discarded by the transport as a timed out one, its late response too.
    """

    def __init__(self, base_transport, *, probe_timeout: float, **kwargs):
        super().__init__(base_transport, **kwargs)
        self.probe_timeout = probe_timeout
        self.failing_units: set[int] = set()    # the unit ids probed by one request, set by ModbusScanner

    def set_failing(self, unit_id: int, failing: bool):
        if failing:
            self.failing_units.add(unit_id)
        else:
            self.failing_units.discard(unit_id)

    async def send_and_receive(self, unit_id, pdu):
        if unit_id not in self.failing_units:
            return await super().send_and_receive(unit_id, pdu)
        async with self._communication_lock:
            try:
                return await asyncio.wait_for(self._reconnect_send_and_receive(unit_id, pdu), self.probe_timeout)
            except TimeoutError as E:
                # wait_for has no text, the transport says the timeout
                raise TimeoutError(f"No response to the probe after {self.probe_timeout} seconds") from E
            finally:
                self._last_request_finished_at = time.monotonic()
