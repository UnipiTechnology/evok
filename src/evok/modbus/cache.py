import logging
import time
from dataclasses import dataclass, field

from tmodbus import AsyncModbusClient
from tmodbus.exceptions import TModbusError

logger = logging.getLogger(__name__)

MAX_READ_COUNT = 125  # registers read by one Modbus request


class ENoCacheRegister(Exception):
    """The register was not read yet"""


class EUnknownRegister(Exception):
    """The registers are not in one register block, an error of the hardware definition

    Not a ValueError, the API reports it as an error of the server, not of the request.
    """


@dataclass
class RegisterGroup:
    address: int
    count: int
    f_divider: int = 1
    f_counter: int = 0
    values: list[int | None] = field(init=False)  # None before the first read
    # the written registers kept by the reads: address -> (value, time.monotonic() until it is kept), see pin()
    pins: dict[int, tuple[int, float]] = field(init=False, default_factory=dict)

    def __post_init__(self):
        self.values = [None] * self.count

    def is_member(self, address: int, count: int = 1) -> bool:
        return self.address <= address and self.address + self.count >= address + count

    def update(self, values, address=None, read=False):
        """Set the values of the registers from address, the registers out of the group are skipped;
        a read keeps the pinned values, an expired pin is dropped and the read value is used
        """
        start = self.address if address is None else address
        for i, value in enumerate(values):
            if self.is_member(start + i):
                self.values[start + i - self.address] = value
        if read and self.pins:
            now = time.monotonic()
            for pinned, (value, until) in list(self.pins.items()):
                if until > now:
                    self.values[pinned - self.address] = value
                elif start <= pinned < start + len(values):
                    del self.pins[pinned]

    def pin(self, address: int, value: int, until: float):
        """Keep the written value of the register until the time, a read before it does not overwrite it"""
        if self.is_member(address):
            self.pins[address] = (value, until)
            self.values[address - self.address] = value

    def pin_expired(self) -> bool:
        """A pin has expired, the group is read by the next scan"""
        now = time.monotonic()
        return any(until <= now for _value, until in self.pins.values())

    def clear_counter(self):
        self.f_counter = 0

    def tick_counter(self):
        self.f_counter = self.f_divider - 1 if self.f_counter == 0 else self.f_counter - 1


def _make_group(block: dict) -> RegisterGroup:
    """A register block of a hardware definition, raise ValueError if it is invalid"""

    def positive_int(name, minimum):
        value = block.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"Register block {block}: '{name}' must be an integer >= {minimum}")
        return value

    if "frequency" in block:
        # frequency was the old name, the block is read in every scan_divider-th scan, it is not a frequency
        if "scan_divider" in block:
            raise ValueError(
                f"Register block {block}: 'frequency' is a deprecated alias of 'scan_divider', do not set both"
            )
        logger.warning(f"Register block {block}: 'frequency' is deprecated, rename it to 'scan_divider'")
        block = {**block, "scan_divider": block["frequency"]}
    if block.get("type", "holding") not in ("holding", "input"):
        raise ValueError(f"Register block {block}: unknown type '{block['type']}', use 'holding' or 'input'")
    group = RegisterGroup(
        address=positive_int("start_reg", 0), count=positive_int("count", 1), f_divider=positive_int("scan_divider", 1)
    )
    # a block is read by one request, a larger one stopped the scan of the unit by an error of the request
    if group.count > MAX_READ_COUNT:
        raise ValueError(f"Register block {block}: 'count' must be at most {MAX_READ_COUNT}, split the block")
    if group.address + group.count > 0x10000:
        raise ValueError(f"Register block {block}: the registers must be at most 65535")
    return group


class ModbusCacheMap:
    def __init__(self, modbus_reg_map, modbus_client):
        self.modbus_client: AsyncModbusClient = modbus_client
        # time.monotonic() of the last read, None before the first successful scan; the clock of the system
        # can jump, e.g. by NTP after the start of a controller without RTC
        self.last_comm_time: float | None = None
        # the error of the last scan, None after a successful one
        self.scan_error: Exception | None = None
        self.groups = []
        self.igroups = []
        for block in modbus_reg_map:
            group = _make_group(block)
            groups = self.igroups if block.get("type") == "input" else self.groups
            # a register is read from the first group, the copy in an overlapping one would not be used
            for other in groups:
                if group.address < other.address + other.count and other.address < group.address + group.count:
                    raise ValueError(
                        f"Register block {block} overlaps the block of registers "
                        f"{other.address}..{other.address + other.count - 1}"
                    )
            groups.append(group)

    async def do_scan(self, initial: bool = False, all_groups: bool = False) -> bool:
        """Read the groups by their scan_divider, with all_groups read all of them and keep their counters,
        the scan after a change does not shift the phase of the slow groups
        """
        if initial:
            for group in self.groups + self.igroups:
                group.clear_counter()
        # a group with an expired pin is read also out of its scan_divider, its counter is not changed by it
        if not await self._read_groups(
            lambda group, is_input: all_groups or group.f_counter == 0 or group.pin_expired()
        ):
            return False
        # the counters are ticked after the whole scan, a failed scan is repeated with the same groups,
        # the slow groups keep their phase
        if not all_groups:
            for group in self.groups + self.igroups:
                group.tick_counter()
        return True

    async def read_changed(self, registers: set[tuple[int, bool]]) -> bool:
        """Read the groups read by every scan (scan_divider 1) and the groups of the registers (address,
        is_input), e.g. after a change, and keep the counters; at least one group, the read after a failed
        write finds whether the unit responds
        """

        def wanted(group, is_input):
            return group.f_divider == 1 or any(
                input_ == is_input and group.is_member(address) for address, input_ in registers
            )

        if not any(wanted(group, False) for group in self.groups) and not any(
            wanted(group, True) for group in self.igroups
        ):
            # e.g. a coil which is not read, on a unit without a group read by every scan
            first = next(iter(self.groups + self.igroups), None)
            return await self._read_groups(lambda group, is_input: group is first)
        return await self._read_groups(wanted)

    def pin(self, index: int, values, until: float, is_input: bool = False):
        """Keep the written values of the registers from index until the time, e.g. of a unit which sets them
        with a delay: the reads before it do not overwrite them, the first scan after it reads their group
        """
        for i, value in enumerate(values):
            for group in self.igroups if is_input else self.groups:
                group.pin(index + i, value, until)

    async def _read_groups(self, wanted) -> bool:
        """Read the groups wanted(group, is_input), False after a communication error"""
        read = 0
        try:
            for groups, func, is_input in (
                (self.groups, self.modbus_client.read_holding_registers, False),
                (self.igroups, self.modbus_client.read_input_registers, True),
            ):
                for group in groups:
                    if wanted(group, is_input):
                        group.update(await func(group.address, quantity=group.count), read=True)
                        read += 1

        except (TModbusError, TimeoutError) as E:
            # also the retries of the transport (RequestRetryFailedError), a noise on RS485 (CRCError)
            # and the exception responses of the unit, e.g. an address out of its registers
            self.scan_error = E
            return False

        # a scan without a read, e.g. of a unit without register blocks, is not a communication
        if read > 0:
            self.last_comm_time = time.monotonic()
        self.scan_error = None
        return True

    def _find_group(self, address: int, count: int, is_input: bool) -> RegisterGroup:
        """The block of all count registers, a value over two blocks would be never cached"""
        for group in self.igroups if is_input else self.groups:
            if group.is_member(address, count):
                return group
        kind = "input" if is_input else "holding"
        raise EUnknownRegister(f"The {kind} registers {address}..{address + count - 1} are not in one register block")

    def get_register(self, index, count=1, is_input=False):
        group = self._find_group(index, count, is_input)
        offset = index - group.address
        values = group.values[offset : offset + count]
        for i, value in enumerate(values):
            if value is None:
                raise ENoCacheRegister(f"No cached value of register {index + i}")
        return values

    def set_register(self, index, values, is_input=False, read=False):
        """Update cached registers after a successful write or read, the registers out of the blocks are skipped;
        a read keeps the pinned values
        """
        for group in self.igroups if is_input else self.groups:
            group.update(values, index, read)

    async def get_register_async(self, index, count=1, is_input=False):
        """Read the registers from the unit, also the ones out of the register blocks; the pinned values
        are returned, e.g. a read-modify-write of a bit after a write the unit has not set yet
        """
        if is_input:
            vals = await self.modbus_client.read_input_registers(index, quantity=count)
        else:
            vals = await self.modbus_client.read_holding_registers(index, quantity=count)
        self.set_register(index, vals, is_input, read=True)
        pinned = {
            address: value
            for group in (self.igroups if is_input else self.groups)
            for address, (value, _until) in group.pins.items()
        }
        return [pinned.get(index + i, value) for i, value in enumerate(vals)]
