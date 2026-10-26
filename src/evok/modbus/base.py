from ..blocks import sequencer
from ..devices import Devices
from ..errors import SequenceRunning
from .client import Client


class IODevice:
    """Base class of the IO devices on a Modbus unit

    Subclasses set `devtype` and implement full() and set()
    """

    devtype = None

    def __init__(self, circuit, client: Client, major_group=0):
        self.alias = ""
        self.circuit = circuit
        self.client = client
        self.major_group = major_group

    def full(self) -> dict:
        """Return the complete state of the device"""
        raise NotImplementedError

    def get(self):
        return self.full()

    async def set(self, alias=None, **kwargs) -> None:
        """Change the device settings, the caller reads the new state by full()"""
        raise NotImplementedError

    def set_alias(self, alias):
        """Set the alias if it is given"""
        if alias is not None:
            Devices.set_alias(alias, self)

    def _with_alias(self, ret: dict) -> dict:
        """Add the alias to a state dict if the device has one"""
        if self.alias != "":
            ret["alias"] = self.alias
        return ret

    def _with_common(self, ret: dict) -> dict:
        """Add the communication with the unit of the device (comm, last_comm) and its alias, the last items
        of the state; the value of a unit which does not respond is the last known one, comm tells it
        """
        comm = getattr(self.client, "comm", None)
        if comm is not None:
            ret["comm"] = comm()
            ret["last_comm"] = self.client.last_comm()
        return self._with_alias(ret)


async def set_devices(
    assignments: list[tuple], states: dict | None = None, sequences: dict | None = None
) -> list[dict]:
    """Set the devices by the params of assignments [(device, kw)], return their states in the same order

    The devices of a Modbus unit are set under the lock of the unit by Client.change(), the unit
    is read and the states follow the writes. The units are set one after another, in the order
    of their first assignment, the other devices one by one. A change of only the alias does not
    write the unit, it is set also on an unavailable unit.

    On an error, states (index of the assignment: state) has the states of the assignments done
    before it, also of its unit, the units after it are not set.

    set() of a device on a Modbus unit runs under the lock of its unit, it must not call set_devices()
    or Client.change() of the same unit: the lock is not reentrant, it would wait for itself forever.

    A change of a device other than its alias is refused by SequenceRunning while a sequence of the sequencer
    of blocks runs for it, e.g. a pulse; it is cancelled by the sequencer device. sequences {device: Sequence}
    replace it, e.g. a new pulse: the sequence of the device is started after its successful set() under
    the lock of the unit, the replaced one is cancelled and its waiting step writes nothing; a failed change
    leaves it running, it writes its final state.
    """
    sequences = sequences or {}
    states = {} if states is None else states
    units: dict = {}
    for index, (device, kw) in enumerate(assignments):
        unit = device.client if isinstance(device, IODevice) else device
        units.setdefault(unit, []).append((index, device, kw))

    _check_aliases(units)

    for unit, items in units.items():
        done = []

        async def operation():
            for index, device, kw in items:
                # under the lock of the unit, as the steps of the sequence
                if set(kw) - {"alias"} and sequencer.is_running(device) and device not in sequences:
                    raise SequenceRunning(
                        f"{str(device.devtype).upper()} {device.circuit}: a sequence of "
                        f"its sequencer {device.devtype}_{device.circuit} runs, cancel it there"
                    )
                await device.set(**kw)
                if device in sequences:
                    sequencer.start(device, sequences[device])
                done.append((index, device))

        try:
            if isinstance(unit, Client):
                writes = any(set(kw) - {"alias"} for _, _, kw in items)
                await unit.change(
                    operation, check_available=writes, read=writes, devices=[device for _, device, _ in items]
                )
            else:
                await operation()
        finally:
            for index, device in done:
                states[index] = device.full()
    return [states[index] for index in range(len(assignments))]


def _check_aliases(units: dict):
    """Check the aliases of the assignments in the order of their changes, before the first write: an invalid
    alias was refused after the write of the value, the output was switched and the request failed. An alias
    released by an earlier assignment can be taken, an alias taken by an earlier one cannot.
    """
    planned: dict = {}  # the alias of a device after the earlier assignments
    free: set[str] = set()
    taken: set[str] = set()
    for items in units.values():
        for _index, device, kw in items:
            # None is not given, set_alias() keeps the alias; "" resets it
            if kw.get("alias") is None:
                continue
            alias = kw["alias"]
            current = planned.get(device, device.alias)
            if alias == current:
                continue
            if alias != "":
                # first, an alias which is not a string is invalid, e.g. a list is not hashable for taken
                Devices.check_alias(alias, device, free)
                if alias in taken:
                    raise ValueError(f"Duplicate alias {alias}")
                taken.add(alias)
                free.discard(alias)
            if current:
                free.add(current)
                taken.discard(current)
            planned[device] = alias
