import asyncio
import contextlib
import functools
import logging
import struct
import time
from math import isfinite
from typing import Literal

from tmodbus import AsyncModbusClient
from tmodbus.exceptions import InvalidResponseError, TModbusError
from tmodbus.utils.order_aware_struct import OrderAwareStruct

from ..devices import devents
from ..errors import UnitCommunicationError, UnitUnavailable, describe_error, root_cause
from .cache import ModbusCacheMap

logger = logging.getLogger(__name__)

RESTART_WAIT = 0.1  # s, the wait after a write after which the unit restarts, before it is read
# s, the serial buses of the unit are held after its restart or the save of its settings, a request
# on the serial port served by the unit corrupts the write of its flash (a bug of the firmware)
SERIAL_HOLD_TIME = 0.5
# s, a register written by a change is kept in the cache by the reads during it, then its block is read by
# the periodic scan; a unit may set a written register with a delay, e.g. the mode of an AI of xS52 in 0.3..0.8 s
REREAD_DELAY = 1.0

UINT16 = struct.Struct(">H")
INT16 = struct.Struct(">h")
FLOAT32_BE = OrderAwareStruct(">f")
FLOAT32_LE = OrderAwareStruct(">f", word_order="little")
INT32_BE = OrderAwareStruct(">i")
INT32_LE = OrderAwareStruct(">i", word_order="little")
UINT32_BE = OrderAwareStruct(">I")
UINT32_LE = OrderAwareStruct(">I", word_order="little")

FLOAT32_WORD_ORDER = {"big": FLOAT32_BE, "little": FLOAT32_LE}
UINT32_WORD_ORDER = {"big": UINT32_BE, "little": UINT32_LE}
INT32_WORD_ORDER = {"big": INT32_BE, "little": INT32_LE}


def from_registers(fmt: struct.Struct, registers):
    """Decode a value from a list of 16-bit registers"""
    return fmt.unpack(struct.pack(f">{len(registers)}H", *registers))[0]


def to_registers(fmt: struct.Struct, value):
    """Encode a value into a list of 16-bit registers"""
    data = fmt.pack(value)
    return list(struct.unpack(f">{len(data) // 2}H", data))


class Client:
    """The registers of a Modbus unit and its devices

    The changes of the devices of the unit run under its lock and in the session of the unit on its bus
    (BusTransport.session()): a change writes, then reads the register blocks and checks the devices,
    so their states and events follow the writes at once; the scan of the unit waits for the session,
    it does not read between the writes of a change. The cache is updated in the order of the requests
    on the bus, a read sent before a write does not overwrite the read after it.
    """

    def __init__(self, name: str, mb_client: AsyncModbusClient, cache: ModbusCacheMap):
        """name of the unit for the errors, e.g. its name in the configuration, the transport and the address"""
        self.name = name
        self.cache = cache
        # set by ModbusScanner by scan_enabled; without a periodic scan a change reads a failed unit again
        self.periodic_scan = True
        self.mb_client = mb_client
        # the serial buses (BusTransport) of the ports served by the unit, the option serial_ports of the device,
        # sorted by their ports; held by write_coil_without_response()
        self.serial_buses: list = []
        # the transport with the sessions of the units (BusTransport), None e.g. for a fake unit of the tests
        transport = getattr(mb_client, "transport", None)
        self._bus = transport if hasattr(transport, "session") else None
        self.eventable_devices = []  # the devices with check_new_data()
        self.devices = []  # all devices of the unit, also without check_new_data()
        self.failing_devices = set()  # logged once, until they check new data again
        self.sent_aliases = {}  # the alias of each device by the last check, Devices.set_alias() sends no event
        # the changes of the unit, also the scans on a transport without the sessions; not reentrant,
        # set() of a device must not change the unit again
        self.lock = asyncio.Lock()
        # the registers (address, is_input) written by the running change, None reads all blocks after it
        self._written: set[tuple[int, bool]] | None = None
        # a change runs, the scan does not check the devices between its writes, the change checks them
        self._changing = False
        # comm by the last event of the devices, a change sends all of them; the devices are created after
        # a successful scan
        self.sent_comm = "ok"

    def comm(self) -> str:
        """The communication with the unit: ok, timeout (the unit does not respond) or error (e.g. a CRC error,
        an exception response of the unit, the port), by the root cause of the error of its last scan
        """
        error = self.cache.scan_error
        if error is None:
            return "ok"
        return "timeout" if isinstance(root_cause(error), TimeoutError) else "error"

    def last_comm(self) -> float | None:
        """Seconds since the last successful communication with the unit, None before it"""
        last = self.cache.last_comm_time
        return None if last is None else round(time.monotonic() - last, 3)

    def read_registers(self, index: int, count: int = 1, is_input: bool = False) -> list[int]:
        """Return the cached values of count registers, the datatypes are decoded by the accessors"""
        return self.cache.get_register(index, count, is_input=is_input)

    async def write_coil_without_response(self, coil: int, value: int, wait: float | None = None) -> bool:
        """Write a coil after which the unit restarts, e.g. its reset or the save of its settings, it may not
        respond: the coil is written once without the retries, a missing or a broken response is not an error;
        wait for the restart before the unit is read. Return True if the unit responded.

        The serial buses of the ports served by the unit (serial_buses) are held from before the write until
        SERIAL_HOLD_TIME after it, a request on the port corrupts the write of the flash of the unit.
        """
        single_request = getattr(getattr(self.mb_client, "transport", None), "single_request", None)
        async with contextlib.AsyncExitStack() as held:
            # in the order of their ports, two units holding the same buses do not hold one each and wait
            # for the other; the units of MODBUSTCP buses only, their own bus is not held
            for bus in self.serial_buses:
                await held.enter_async_context(bus.hold())
            try:
                with single_request(self.mb_client.unit_id) if single_request else contextlib.nullcontext():
                    await self.mb_client.write_single_coil(coil, value)
                responded = True
            except Exception as E:
                if not isinstance(root_cause(E), (TimeoutError, InvalidResponseError)):
                    raise
                logger.debug(f"Unit {self.name}: no response to the write of coil {coil}, it restarts: {E}")
                responded = False
            finally:
                # also after an error, e.g. a lost connection: the coil may have been sent, the unit writes its flash
                if self.serial_buses:
                    await asyncio.sleep(SERIAL_HOLD_TIME)
        # the unit restarted or saved its settings, a change reads all its blocks, the written values are not kept
        self._written = None
        self.cache.clear_pins()
        await asyncio.sleep(RESTART_WAIT if wait is None else wait)
        return responded

    async def write_registers(self, index: int, values: list[int], cache: bool = True, pin: bool = True):
        """Write holding registers and update the cache, so the next check does not see a stale value;
        without cache the caller updates it, e.g. after all writes of a setting

        The written values are kept in the cache for REREAD_DELAY (ModbusCacheMap.pin()): a unit may set
        them with a delay and a read before it returns the old ones, e.g. the mode of an AI of xS52; then
        the periodic scan reads them, a value refused by the unit is seen then. Without pin, e.g. a counter
        which the unit changes itself, or on a unit without the periodic scan, the read shows the unit.
        """
        if len(values) == 1:
            await self.mb_client.write_single_register(index, values[0])
        else:
            await self.mb_client.write_multiple_registers(index, values)
        if cache:
            self.cache.set_register(index, values)
        if pin and self.periodic_scan:
            # the reads before the unit sets them do not overwrite them, the periodic scan reads them after it;
            # a unit without the periodic scan shows them by the read after the change
            self.cache.pin(index, values, time.monotonic() + REREAD_DELAY)
        else:
            # an older pin of the registers would overwrite the written values
            self.cache.unpin(index, len(values))
        if self._written is not None:
            self._written.update((index + i, False) for i in range(len(values)))

    async def do_scan(self) -> bool:
        """The periodic scan of the unit, it waits for a change of the unit by the session of its bus"""
        async with self._scan_lock():
            return await self._scan()

    def _scan_lock(self):
        """The lock of the unit for a scan on a transport without the sessions, e.g. a fake unit of the tests"""
        return contextlib.nullcontext() if self._bus is not None else self.lock

    async def change(self, operation, check_available: bool = True, read: bool = True, devices=None):
        """Run the writes of operation() under the lock of the unit, then read all register blocks
        and check the devices, also after a failed operation, its writes before the error are seen;
        without read, e.g. a change of only the alias, the devices are checked without a read

        With devices, the changed devices of the unit, only the blocks read by every scan, the blocks
        of the states of the devices and of the written registers are read; the other blocks are read
        by the periodic scan by their scan_divider. A restart of the unit (write_coil_without_response)
        reads all blocks.

        A unit which failed its last scan raises UnitUnavailable without a write, check_available=False
        writes anyway, e.g. the end of a pulse. A unit without a periodic scan is read first, nothing else
        would read it again, its failed scan after a change refused all next changes.

        The changes of the unit run one after another under its lock. The change runs in the session
        of the unit on its bus: its requests go before the scans, the scan of the unit waits until the change
        ends, it does not read the unit between the writes; a running scan does not delay the change.
        """
        # the session under the lock: each change ends its session, the scans get the bus between the changes
        async with self.lock:
            with self._bus.session(self.mb_client.unit_id) if self._bus is not None else contextlib.nullcontext():
                self._changing = True
                try:
                    await self._change(operation, check_available, read, devices)
                finally:
                    self._changing = False

    async def _change(self, operation, check_available: bool, read: bool, devices):
        if check_available and self.cache.scan_error is not None:
            if self.periodic_scan or not await self.cache.do_scan(all_groups=True):
                raise UnitUnavailable(f"Unit {self.name} is not available: {describe_error(self.cache.scan_error)}")
        self._written = None if devices is None else set()
        try:
            await operation()
        except (TModbusError, TimeoutError) as E:
            # it was an internal error with a traceback, the unit did not respond or refused the request
            raise UnitCommunicationError(f"Unit {self.name}: {describe_error(E)}") from E
        finally:
            written, self._written = self._written, None
            if written:
                # kept from the end of the change, a long one does not lose the pins of its first writes
                self.cache.renew_pins(written, time.monotonic() + REREAD_DELAY)
            if read:
                if written is None:
                    await self._scan(self.cache.do_scan(all_groups=True))
                else:
                    registers = written | {register for device in devices for register in device_registers(device)}
                    await self._scan(self.cache.read_changed(registers))
            else:
                await self._check_devices()

    async def check_devices(self):
        """Check the devices by the registers read before, e.g. by the first scan before they were created;
        a running change checks them at its end
        """
        async with self._scan_lock():
            if not self._changing:
                await self._check_devices()

    async def _scan(self, read=None) -> bool:
        """Read the register blocks by read, the coroutine of the cache, by default the periodic scan, then
        send the changed devices as one event; the periodic scan during a change does not check them
        """
        periodic = read is None
        if not await (self.cache.do_scan() if periodic else read):
            # the values are stale, the devices are sent with the changed comm
            if not (periodic and self._changing):
                self.send_comm_change()
            return False
        if not (periodic and self._changing):
            await self._check_devices()
        return True

    def send_comm_change(self):
        """Send all devices as one event if comm has changed since the last event, e.g. a lost unit"""
        if self.comm() != self.sent_comm:
            self.sent_comm = self.comm()
            devices = list(dict.fromkeys(self.eventable_devices + self.devices))
            if devices:
                devents.status(Proxy(devices))

    async def _check_devices(self):
        """Send the devices changed since their last check as one event, also by their alias

        check_new_data() of the devices does no I/O, the check of a scan and of a change are not interleaved.
        """
        changeset = []
        for device in dict.fromkeys(self.eventable_devices + self.devices):
            changed = False
            try:
                changed = hasattr(device, "check_new_data") and await device.check_new_data() is True
            except Exception:
                # the error repeats on every scan, do not flood the log
                if device not in self.failing_devices:
                    self.failing_devices.add(device)
                    logger.exception(
                        f"Error while checking new data in device '{device.devtype}_{device.circuit}', "
                        "next errors are not logged until it works again"
                    )
            else:
                if device in self.failing_devices:
                    self.failing_devices.discard(device)
                    logger.info(f"Device '{device.devtype}_{device.circuit}' checks new data again")
            # a new or deleted alias, check_new_data() does not compare it; a device not checked yet
            # has no alias sent, its first check sends it anyway
            alias = getattr(device, "alias", "")
            if self.sent_aliases.get(device, "") != alias:
                self.sent_aliases[device] = alias
                changed = True
            if changed:
                changeset.append(device)

        if self.comm() != self.sent_comm:
            # also a recovered unit, all devices are sent
            self.sent_comm = self.comm()
            changeset = list(dict.fromkeys(self.eventable_devices + self.devices))
        if len(changeset) > 0:
            proxy = Proxy(changeset)
            devents.status(proxy)


class Proxy:
    """The changed devices of one scan, sent as one event; their states are made once for all receivers"""

    def __init__(self, changeset):
        self.changeset = changeset

    @functools.cached_property
    def states(self):
        return [c.full() for c in self.changeset]

    def full(self):
        return self.states


def device_registers(device) -> set[tuple[int, bool]]:
    """The registers (address, is_input) of the state of a device, e.g. of an output written by its coil:
    its accessors named by state_accessors ("accessor" by default), also of the other modes, the mode
    is switched by the check after the read; its settings written by write_registers() are read as the
    written registers
    """
    registers = set()
    for name in getattr(device, "state_accessors", ("accessor",)):
        accessor = getattr(device, name, None)
        if isinstance(accessor, Accessor) and accessor.index is not None:
            registers.update((accessor.index + i, accessor.is_input) for i in range(accessor.count))
    return registers


class Accessor:
    """Reads a value of a given datatype from the cache of a Client
    and applies the linear transformation val * ratio + offset
    and rounding to decimals. Writes apply the inverse transformation.
    The datatype is decoded from count registers by the struct fmt.
    Base class reads nothing and cannot write (unknown datatype).
    """

    datatype = None
    raw_range = None  # (min, max) of integer datatypes, None for float
    fmt: struct.Struct | None = None
    count = 1

    def __init__(self, index: int, is_input: bool = False, *, ratio=1, offset=0, decimals=None, pin=True):
        """pin=False: a write is not pinned in the cache (Client.write_registers()), e.g. a counter"""
        if ratio == 0:
            raise ValueError(f"Ratio of register {index} cannot be 0")
        self.index = index
        self.is_input = is_input
        self.pin = pin
        self.ratio = ratio
        self.offset = offset
        self.decimals = decimals

    def params(self) -> dict:
        return {"is_input": self.is_input, "ratio": self.ratio, "offset": self.offset, "decimals": self.decimals}

    def refactor(self, datatype: str = "uint16", ratio=1, offset=0, decimals=None, word_order=None) -> "Accessor":
        """Return a new accessor of the same register. Only index and is_input
        are taken from this accessor, the other parameters come from the call.
        """
        return AccessorFactory.get(
            self.index,
            datatype,
            is_input=self.is_input,
            ratio=ratio,
            offset=offset,
            decimals=decimals,
            word_order=word_order,
        )

    def read_raw(self, client: Client) -> int | float | None:
        if self.fmt is None:
            return None
        return from_registers(self.fmt, client.read_registers(self.index, self.count, is_input=self.is_input))

    def read(self, client: Client) -> int | float | None:
        val = self.read_raw(client)
        if val is None:
            return None
        if self.ratio != 1 or self.offset != 0:
            val = val * self.ratio + self.offset
        if self.decimals is not None:
            val = round(val, self.decimals)
        return val

    async def write_raw(self, client: Client, raw):
        if self.fmt is None:
            raise ValueError(f"Cannot write unknown datatype to register {self.index}")
        try:
            registers = to_registers(self.fmt, raw)
        except OverflowError:  # float32, the integer datatypes are checked by raw_range
            raise ValueError(f"Value {raw} out of range for {self.datatype} register {self.index}") from None
        await client.write_registers(self.index, registers, pin=self.pin)

    async def write(self, client: Client, value):
        """Write the value converted by the inverse transformation (val - offset) / ratio,
        integer datatypes are rounded and checked against their range
        """
        if self.is_input:
            raise ValueError(f"Input register {self.index} is read-only")
        raw = value
        if self.ratio != 1 or self.offset != 0:
            raw = (raw - self.offset) / self.ratio
        if not isfinite(raw):
            raise ValueError(f"Value {value} out of range for {self.datatype} register {self.index}")
        if self.raw_range is not None:
            raw = round(raw)
            low, high = self.raw_range
            if not low <= raw <= high:
                raise ValueError(f"Value {value} out of range for {self.datatype} register {self.index}")
        await self.write_raw(client, raw)


class AccessorU16(Accessor):
    datatype = "uint16"
    raw_range = (0, 0xFFFF)
    fmt = UINT16


class AccessorI16(Accessor):
    datatype = "int16"
    raw_range = (-0x8000, 0x7FFF)
    fmt = INT16


class AccessorBit(Accessor):
    """Reads a bit selected by mask from a 16-bit register, returns 1 if any masked bit is set, else 0.
    Writing 1 sets all masked bits, 0 clears them, other bits of the register are kept.
    """

    datatype = "bit"
    raw_range = (0, 1)

    def __init__(self, index: int, mask: int, is_input: bool = False, **kwargs):
        super().__init__(index, is_input, **kwargs)
        self.mask = mask

    def params(self) -> dict:
        return dict(super().params(), mask=self.mask)

    def read_raw(self, client: Client) -> int:
        return 1 if client.read_registers(self.index, is_input=self.is_input)[0] & self.mask else 0

    async def write_raw(self, client: Client, raw: int):
        """Read-modify-write, the register is read from the unit, not from the cache"""
        curr = (await client.cache.get_register_async(self.index))[0]
        await client.write_registers(self.index, [curr | self.mask if raw else curr & ~self.mask])


class Accessor32(Accessor):
    """Base for values in two registers,
    word_order "little" = low word first, "big" = high word first
    """

    count = 2
    formats: dict[str, struct.Struct]  # the format of each word order

    def __init__(
        self, index: int, is_input: bool = False, *, word_order: Literal["big", "little"] = "little", **kwargs
    ):
        if word_order not in self.formats:
            raise ValueError(f"Unknown word order '{word_order}'")
        super().__init__(index, is_input, **kwargs)
        self.word_order = word_order
        self.fmt = self.formats[word_order]

    def params(self) -> dict:
        return dict(super().params(), word_order=self.word_order)


class AccessorU32(Accessor32):
    datatype = "uint32"
    raw_range = (0, 0xFFFFFFFF)
    formats = UINT32_WORD_ORDER


class AccessorI32(Accessor32):
    datatype = "int32"
    raw_range = (-0x80000000, 0x7FFFFFFF)
    formats = INT32_WORD_ORDER


class AccessorFloat32(Accessor32):
    datatype = "float32"
    formats = FLOAT32_WORD_ORDER


class AccessorFactory:
    accessor_classes = {
        "uint16": AccessorU16,
        "int16": AccessorI16,
        "signed16": AccessorI16,  # name used by data_point in hw definitions
        "uint32": AccessorU32,
        "int32": AccessorI32,
        "float32": AccessorFloat32,
    }

    @classmethod
    def get(
        cls,
        index: int,
        datatype: str = "uint16",
        *,
        is_input: bool = False,
        ratio=1,
        offset=0,
        decimals=None,
        word_order=None,
    ) -> Accessor:
        """word_order is accepted only by 32-bit datatypes"""
        kwargs = {"ratio": ratio, "offset": offset, "decimals": decimals}
        accessor_cls = cls.accessor_classes.get(datatype)
        if accessor_cls is None:
            logger.warning(f'Unknown datatype "{datatype}" in AccessorFactory index={index}')
            return Accessor(index, is_input, **kwargs)
        if word_order is not None:
            if not issubclass(accessor_cls, Accessor32):
                raise ValueError(f'Datatype "{datatype}" does not support word_order')
            kwargs["word_order"] = word_order
        return accessor_cls(index, is_input, **kwargs)
