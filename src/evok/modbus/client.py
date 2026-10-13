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

RESTART_WAIT = 0.1      # s, the wait after a write after which the unit restarts, before it is read

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
    """ Decode a value from a list of 16-bit registers """
    return fmt.unpack(struct.pack(f">{len(registers)}H", *registers))[0]


def to_registers(fmt: struct.Struct, value):
    """ Encode a value into a list of 16-bit registers """
    data = fmt.pack(value)
    return list(struct.unpack(f">{len(data) // 2}H", data))


class Client:
    """ The registers of a Modbus unit and its devices

        The scans and the changes of the devices of the unit run under its lock: a change writes,
        then reads all register blocks and checks the devices, so their states and events follow
        the writes at once and a scan does not read between the writes of a change.
    """

    def __init__(self, name: str,
                 mb_client: AsyncModbusClient,
                 cache: ModbusCacheMap):
        """ name of the unit for the errors, e.g. its name in the configuration, the transport and the address """
        self.name = name
        self.cache = cache
        # set by ModbusScanner by scan_enabled; without a periodic scan a change reads a failed unit again
        self.periodic_scan = True
        self.mb_client = mb_client
        self.eventable_devices = []     # the devices with check_new_data()
        self.devices = []               # all devices of the unit, also without check_new_data()
        self.failing_devices = set()    # logged once, until they check new data again
        self.sent_aliases = {}          # the alias of each device by the last check, Devices.set_alias() sends no event
        self.lock = asyncio.Lock()      # not reentrant, set() of a device must not change the unit again
        # comm by the last event of the devices, a change sends all of them; the devices are created after
        # a successful scan
        self.sent_comm = 'ok'

    def comm(self) -> str:
        """ The communication with the unit: ok, timeout (the unit does not respond) or error (e.g. a CRC error,
            an exception response of the unit, the port), by the root cause of the error of its last scan
        """
        error = self.cache.scan_error
        if error is None:
            return 'ok'
        return 'timeout' if isinstance(root_cause(error), TimeoutError) else 'error'

    def last_comm(self) -> float | None:
        """ Seconds since the last successful communication with the unit, None before it """
        last = self.cache.last_comm_time
        return None if last is None else round(time.monotonic() - last, 3)

    def read_registers(self, index: int, count: int = 1, is_input: bool = False) -> list[int]:
        """ Return the cached values of count registers, the datatypes are decoded by the accessors """
        return self.cache.get_register(index, count, is_input=is_input)

    async def write_coil_without_response(self, coil: int, value: int, wait: float | None = None) -> bool:
        """ Write a coil after which the unit restarts, e.g. its reset or the save of its settings, it may not
            respond: the coil is written once without the retries, a missing or a broken response is not an error;
            wait for the restart before the unit is read. Return True if the unit responded.
        """
        single_request = getattr(getattr(self.mb_client, 'transport', None), 'single_request', None)
        try:
            with single_request(self.mb_client.unit_id) if single_request else contextlib.nullcontext():
                await self.mb_client.write_single_coil(coil, value)
            responded = True
        except Exception as E:
            if not isinstance(root_cause(E), (TimeoutError, InvalidResponseError)):
                raise
            logger.debug(f"Unit {self.name}: no response to the write of coil {coil}, it restarts: {E}")
            responded = False
        await asyncio.sleep(RESTART_WAIT if wait is None else wait)
        return responded

    async def write_registers(self, index: int, values: list[int]):
        """ Write holding registers and update the cache, so the next check does not see a stale value """
        if len(values) == 1:
            await self.mb_client.write_single_register(index, values[0])
        else:
            await self.mb_client.write_multiple_registers(index, values)
        self.cache.set_register(index, values)

    async def do_scan(self) -> bool:
        """ The periodic scan of the unit """
        async with self.lock:
            return await self._scan()

    async def change(self, operation, check_available: bool = True, read: bool = True):
        """ Run the writes of operation() under the lock of the unit, then read all register blocks
            and check the devices, also after a failed operation, its writes before the error are seen;
            without read, e.g. a change of only the alias, the devices are checked without a read

            A unit which failed its last scan raises UnitUnavailable without a write, check_available=False
            writes anyway, e.g. the end of a pulse. A unit without a periodic scan is read first, nothing else
            would read it again, its failed scan after a change refused all next changes.
        """
        async with self.lock:
            if check_available and self.cache.scan_error is not None:
                if self.periodic_scan or not await self.cache.do_scan(all_groups=True):
                    raise UnitUnavailable(f"Unit {self.name} is not available: {describe_error(self.cache.scan_error)}")
            try:
                await operation()
            except (TModbusError, TimeoutError) as E:
                # it was an internal error with a traceback, the unit did not respond or refused the request
                raise UnitCommunicationError(f"Unit {self.name}: {describe_error(E)}") from E
            finally:
                if read:
                    await self._scan(all_groups=True)
                else:
                    await self._check_devices()

    async def check_devices(self):
        """ Check the devices by the registers read before, e.g. by the first scan before they were created """
        async with self.lock:
            await self._check_devices()

    async def _scan(self, all_groups: bool = False) -> bool:
        """ Read the register blocks, send the changed devices as one event; under the lock """
        if not await self.cache.do_scan(all_groups=all_groups):
            # the values are stale, the devices are sent with the changed comm
            self.send_comm_change()
            return False
        await self._check_devices()
        return True

    def send_comm_change(self):
        """ Send all devices as one event if comm has changed since the last event, e.g. a lost unit """
        if self.comm() != self.sent_comm:
            self.sent_comm = self.comm()
            devices = list(dict.fromkeys(self.eventable_devices + self.devices))
            if devices:
                devents.status(Proxy(devices))

    async def _check_devices(self):
        """ Send the devices changed since their last check as one event, also by their alias; under the lock """
        changeset = []
        for device in dict.fromkeys(self.eventable_devices + self.devices):
            changed = False
            try:
                changed = hasattr(device, 'check_new_data') and await device.check_new_data() is True
            except Exception:
                # the error repeats on every scan, do not flood the log
                if device not in self.failing_devices:
                    self.failing_devices.add(device)
                    logger.exception(f"Error while checking new data in device '{device.devtype}_{device.circuit}', "
                                     "next errors are not logged until it works again")
            else:
                if device in self.failing_devices:
                    self.failing_devices.discard(device)
                    logger.info(f"Device '{device.devtype}_{device.circuit}' checks new data again")
            # a new or deleted alias, check_new_data() does not compare it; a device not checked yet
            # has no alias sent, its first check sends it anyway
            alias = getattr(device, 'alias', '')
            if self.sent_aliases.get(device, '') != alias:
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
    """ The changed devices of one scan, sent as one event; their states are made once for all receivers """

    def __init__(self, changeset):
        self.changeset = changeset

    @functools.cached_property
    def states(self):
        return [c.full() for c in self.changeset]

    def full(self):
        return self.states


class Accessor:
    """ Reads a value of a given datatype from the cache of a Client
        and applies the linear transformation val * ratio + offset
        and rounding to decimals. Writes apply the inverse transformation.
        The datatype is decoded from count registers by the struct fmt.
        Base class reads nothing and cannot write (unknown datatype).
    """
    datatype = None
    raw_range = None  # (min, max) of integer datatypes, None for float
    fmt: struct.Struct | None = None
    count = 1

    def __init__(self, index: int, is_input: bool = False, *,
                 ratio=1, offset=0, decimals=None):
        if ratio == 0:
            raise ValueError(f'Ratio of register {index} cannot be 0')
        self.index = index
        self.is_input = is_input
        self.ratio = ratio
        self.offset = offset
        self.decimals = decimals

    def params(self) -> dict:
        return {"is_input": self.is_input, "ratio": self.ratio,
                "offset": self.offset, "decimals": self.decimals}

    def refactor(self, datatype: str = 'uint16', ratio=1, offset=0, decimals=None,
                 word_order=None) -> "Accessor":
        """ Return a new accessor of the same register. Only index and is_input
            are taken from this accessor, the other parameters come from the call.
        """
        return AccessorFactory.get(self.index, datatype, is_input=self.is_input, ratio=ratio,
                                   offset=offset, decimals=decimals, word_order=word_order)

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
            raise ValueError(f'Cannot write unknown datatype to register {self.index}')
        try:
            registers = to_registers(self.fmt, raw)
        except OverflowError:   # float32, the integer datatypes are checked by raw_range
            raise ValueError(f'Value {raw} out of range for {self.datatype} register {self.index}') from None
        await client.write_registers(self.index, registers)

    async def write(self, client: Client, value):
        """ Write the value converted by the inverse transformation (val - offset) / ratio,
            integer datatypes are rounded and checked against their range
        """
        if self.is_input:
            raise ValueError(f'Input register {self.index} is read-only')
        raw = value
        if self.ratio != 1 or self.offset != 0:
            raw = (raw - self.offset) / self.ratio
        if not isfinite(raw):
            raise ValueError(f'Value {value} out of range for {self.datatype} register {self.index}')
        if self.raw_range is not None:
            raw = round(raw)
            low, high = self.raw_range
            if not low <= raw <= high:
                raise ValueError(f'Value {value} out of range for {self.datatype} register {self.index}')
        await self.write_raw(client, raw)


class AccessorU16(Accessor):
    datatype = 'uint16'
    raw_range = (0, 0xffff)
    fmt = UINT16


class AccessorI16(Accessor):
    datatype = 'int16'
    raw_range = (-0x8000, 0x7fff)
    fmt = INT16


class AccessorBit(Accessor):
    """ Reads a bit selected by mask from a 16-bit register, returns 1 if any masked bit is set, else 0.
        Writing 1 sets all masked bits, 0 clears them, other bits of the register are kept.
    """
    datatype = 'bit'
    raw_range = (0, 1)

    def __init__(self, index: int, mask: int, is_input: bool = False, **kwargs):
        super().__init__(index, is_input, **kwargs)
        self.mask = mask

    def params(self) -> dict:
        return dict(super().params(), mask=self.mask)

    def read_raw(self, client: Client) -> int:
        return 1 if client.read_registers(self.index, is_input=self.is_input)[0] & self.mask else 0

    async def write_raw(self, client: Client, raw: int):
        """ Read-modify-write, the register is read from the unit, not from the cache """
        curr = (await client.cache.get_register_async(self.index))[0]
        await client.write_registers(self.index, [curr | self.mask if raw else curr & ~self.mask])


class Accessor32(Accessor):
    """ Base for values in two registers,
        word_order "little" = low word first, "big" = high word first
    """
    count = 2
    formats: dict[str, struct.Struct]   # the format of each word order

    def __init__(self, index: int, is_input: bool = False, *,
                 word_order: Literal["big", "little"] = "little", **kwargs):
        if word_order not in self.formats:
            raise ValueError(f"Unknown word order '{word_order}'")
        super().__init__(index, is_input, **kwargs)
        self.word_order = word_order
        self.fmt = self.formats[word_order]

    def params(self) -> dict:
        return dict(super().params(), word_order=self.word_order)


class AccessorU32(Accessor32):
    datatype = 'uint32'
    raw_range = (0, 0xffffffff)
    formats = UINT32_WORD_ORDER


class AccessorI32(Accessor32):
    datatype = 'int32'
    raw_range = (-0x80000000, 0x7fffffff)
    formats = INT32_WORD_ORDER


class AccessorFloat32(Accessor32):
    datatype = 'float32'
    formats = FLOAT32_WORD_ORDER


class AccessorFactory:
    accessor_classes = {
        'uint16': AccessorU16,
        'int16': AccessorI16,
        'signed16': AccessorI16,  # name used by data_point in hw definitions
        'uint32': AccessorU32,
        'int32': AccessorI32,
        'float32': AccessorFloat32,
    }

    @classmethod
    def get(cls, index: int, datatype: str = 'uint16', *, is_input: bool = False,
            ratio=1, offset=0, decimals=None, word_order=None) -> Accessor:
        """ word_order is accepted only by 32-bit datatypes """
        kwargs = {"ratio": ratio, "offset": offset, "decimals": decimals}
        accessor_cls = cls.accessor_classes.get(datatype)
        if accessor_cls is None:
            logger.warning(f'Unknown datatype "{datatype}" in AccessorFactory index={index}')
            return Accessor(index, is_input, **kwargs)
        if word_order is not None:
            if not issubclass(accessor_cls, Accessor32):
                raise ValueError(f'Datatype "{datatype}" does not support word_order')
            kwargs['word_order'] = word_order
        return accessor_cls(index, is_input, **kwargs)
