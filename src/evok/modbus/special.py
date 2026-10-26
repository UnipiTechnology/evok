import asyncio
import logging

from ..devices import NV_SAVE, OWPOWER, WATCHDOG, to_bool, to_float
from .base import IODevice
from .client import AccessorU16, Client

logger = logging.getLogger(__name__)


class OwPower(IODevice):
    """The coil disables the power of the 1-Wire bus, value 1 is the bus without power

    The coil is not read from the unit, the value is the last one written, 0 after the start.
    """

    devtype = OWPOWER

    def __init__(self, circuit, client: Client, coil, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.value = 0
        self.checked_value = 0  # the value of the last check, a changed one is sent as an event

    async def check_new_data(self):
        """A value written since the last check, the scan after the change sends it as an event;
        without it a change of the power was sent to no client
        """
        changed = self.value != self.checked_value
        self.checked_value = self.value
        return changed

    def full(self):
        ret = {"dev": "owpower", "circuit": self.circuit, "value": self.value}
        self._with_common(ret)
        return ret

    async def set(self, value=None, alias=None):
        """Sets new on/off status."""
        self.set_alias(alias)
        if value is not None:
            value = int(to_bool(value))  # full() reports 0/1 as the other devices, not true/false
            await self.client.mb_client.write_single_coil(self.coil, bool(value))
            self.value = value


class NvSave(IODevice):
    """Writing value=1 schedules writing of startup data in firmware

    The value is held at 1 for HOLD_TIME seconds after the write,
    a new write is refused until then.
    """

    devtype = NV_SAVE

    HOLD_TIME = 2.0

    def __init__(self, circuit, client: Client, coil, major_group=0):
        super().__init__(circuit, client, major_group)
        self.coil = coil
        self.value = 0
        self.hold_task: asyncio.Task | None = None

    def full(self):
        ret = {"dev": "nv_save", "circuit": self.circuit, "value": self.value}
        self._with_common(ret)
        return ret

    async def _hold(self):
        """Keep the value at 1 for HOLD_TIME, then return it to 0"""
        try:
            await asyncio.sleep(self.HOLD_TIME)
        finally:
            # a cancelled timer must not reset a timer started after it
            if self.hold_task is asyncio.current_task():
                self.value = 0
                self.hold_task = None

    async def set(self, value=None, alias=None):
        """Schedule writing of startup data in firmware if value=1"""
        self.set_alias(alias)
        if value is not None and to_bool(value):
            if self.hold_task is not None:
                raise ValueError(f"NV save {self.circuit} is in progress, try it again later")
            # start the timer before the write, so a concurrent call is refused
            self.value = 1
            self.hold_task = asyncio.create_task(self._hold())
            try:
                # the unit saves its settings and may not respond, a retry would save them again
                await self.client.write_coil_without_response(self.coil, 1)
            except Exception:
                # a task cancelled before it starts does not run its finally block
                self.hold_task.cancel()
                self.hold_task = None
                self.value = 0
                raise


class Watchdog(IODevice):
    devtype = WATCHDOG

    def __init__(self, circuit, client: Client, reg, timeout_reg, reset_coil, major_group=0):
        super().__init__(circuit, client, major_group)
        self.resetvalue = 0
        self.reset_coil = reset_coil
        self.wdwasresetvalue = 0
        self.accessor = AccessorU16(reg)
        self.accessor_timeout = AccessorU16(timeout_reg)

        self.value = None
        self.timeout = None
        self.was_wd_boot_value = None

    def full(self):
        ret = {
            "dev": "wd",
            "circuit": self.circuit,
            "value": self.value,
            "timeout": self.timeout,
            "was_wd_reset": self.was_wd_boot_value,
        }
        self._with_common(ret)
        return ret

    async def check_new_data(self):
        """Bit 0 of the register enables the watchdog, bit 1 is a restart by the watchdog"""
        old_state = (self.value, self.was_wd_boot_value, self.timeout)
        register = self.accessor.read(self.client)
        self.value = register & 0b01
        self.was_wd_boot_value = 1 if register & 0b10 else 0
        self.timeout = self.accessor_timeout.read(self.client)
        return old_state != (self.value, self.was_wd_boot_value, self.timeout)

    async def set(self, value=None, timeout=None, reset=None, nv_save=None, alias=None):
        """Sets new on/off status. Disable pending timeouts

        nv_save is deprecated and not supported, it is rejected before any change: nv_save=0
        saved the settings too, the device nv_save of the unit saves them.
        """
        if nv_save is not None:
            raise ValueError(
                f"WD {self.circuit}: nv_save is deprecated and not supported, use the device nv_save {self.major_group}"
            )
        # all params are checked before any change, e.g. the watchdog enabled with an invalid timeout
        if value is not None:
            value = 1 if to_bool(value) else 0
        if timeout is not None:
            number = to_float(timeout)
            if number != int(number) or number < 0:
                raise ValueError(f"WD {self.circuit}: timeout must be a whole number of ms >= 0, not {timeout}")
            timeout = min(int(number), 65535)
        reset = reset is not None and to_bool(reset)
        self.set_alias(alias)

        if value is not None:
            # the whole register is written, it clears the flag of a restart by the watchdog too
            await self.accessor.write(self.client, value)

        if timeout is not None:
            await self.accessor_timeout.write(self.client, timeout)

        if self.reset_coil >= 0:
            if reset:
                # the unit restarts at once, it does not respond and a retry would restart it again
                await self.client.write_coil_without_response(self.reset_coil, 1)
                logger.info(f"Performed reset of board {self.circuit}")
