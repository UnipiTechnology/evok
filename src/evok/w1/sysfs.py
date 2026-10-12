""" The 1-Wire bus by the subsystem of the kernel, e.g. a DS2482 bound by the device tree

    A master is /sys/bus/w1/devices/w1_bus_master<N>, the kernel searches its bus (every 10 s by default)
    and lists the found slaves in w1_master_slaves, e.g. 28-00000925204e. The values are read from
    the attributes of the slave drivers w1_therm, w1_ds2438, w1_ds2408, w1_ds2413 and w1_ds2406,
    a read blocks until the device answers (a conversion of a DS18B20 takes 750 ms), it runs in a thread.

    The address of a device is the ROM in the order of owserver, e.g. 28.4E2025090000.FF: the family,
    the bytes of the serial number (in the reverse order of the sysfs name) and the CRC. The circuits
    of the found sensors stayed the same as with owserver.
"""
import asyncio
import os

W1_DEVICES = '/sys/bus/w1/devices'

# the device types of the families, w1_therm reads the thermometers
FAMILY_TYPES = {
    0x10: 'DS18S20', 0x22: 'DS1822', 0x28: 'DS18B20', 0x3B: 'DS1825', 0x42: 'DS28EA00',
    0x26: 'DS2438', 0x29: 'DS2408', 0x3A: 'DS2413', 0x12: 'DS2406',
}
THERMOMETERS = (0x10, 0x22, 0x28, 0x3B, 0x42)


def crc8(data: bytes) -> int:
    """ The CRC of the ROM of a 1-Wire device (Dallas/Maxim, x^8 + x^5 + x^4 + 1) """
    crc = 0
    for byte in data:
        for _ in range(8):
            mix = (crc ^ byte) & 1
            crc >>= 1
            if mix:
                crc ^= 0x8C
            byte >>= 1
    return crc


def address_key(address) -> str:
    """ The family and the serial number of a 1-Wire address in the order of owserver, in upper case

        The forms of owserver 28.4E2025090000.FF, without the CRC, the dots or in lower case,
        and the name in sysfs 28-00000925204e are the same device.
    """
    address = str(address).strip()
    if '-' in address:
        family, serial = address.split('-', 1)
        return (family + bytes.fromhex(serial)[::-1].hex()).upper()
    return address.replace('.', '').upper()[:14]


def owfs_address(name: str) -> str:
    """ The address of the sysfs name 28-00000925204e in the form of owserver 28.4E2025090000.FF """
    key = address_key(name)
    return f"{key[:2]}.{key[2:]}.{crc8(bytes.fromhex(key)):02X}"


def masters(root: str | None = None) -> list[str]:
    """ The names of the 1-Wire masters of the kernel, w1_bus_master1, ... """
    root = W1_DEVICES if root is None else root
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return []
    return sorted((name for name in names if name.startswith('w1_bus_master')),
                  key=lambda name: int(name[len('w1_bus_master'):] or 0))


class W1Master:
    """ A master of the kernel, the default one is the first master """

    def __init__(self, name: str | None = None):
        if name is None:
            found = masters()
            if not found:
                raise FileNotFoundError(f"no 1-Wire master in {W1_DEVICES}")
            name = found[0]
        self.name = name
        self.path = os.path.join(W1_DEVICES, name)
        if not os.path.isdir(self.path):
            raise FileNotFoundError(f"1-Wire master '{name}' not found in {W1_DEVICES}")

    async def slaves(self) -> list[str]:
        """ The sysfs names of the slaves found by the kernel, its last search """
        text = await asyncio.to_thread(_read_text, os.path.join(self.path, 'w1_master_slaves'))
        return [line.strip() for line in text.splitlines() if '-' in line]

    def device(self, name: str) -> 'W1Device':
        return W1Device(os.path.join(W1_DEVICES, name))

    def _attribute(self, name):
        return os.path.join(self.path, name)

    def can_search(self) -> bool:
        """ A search can be forced, w1_master_search is writable only by root without a udev rule """
        return os.access(self._attribute('w1_master_search'), os.W_OK)

    async def search(self):
        """ Search the bus at once, the kernel wakes its search thread

            The count of the searches is written back, -1 keeps the continual search of the kernel,
            1 searches once if the search was disabled (0).
        """
        path = self._attribute('w1_master_search')
        count = int(await asyncio.to_thread(_read_text, path))
        await asyncio.to_thread(_write_text, path, f"{count or 1}\n")

    def can_bulk_convert(self) -> bool:
        """ A conversion of all thermometers can be triggered; therm_bulk_read exists only with a thermometer
            of w1_therm on a master and it is writable only by root without a udev rule
        """
        return os.access(self._attribute('therm_bulk_read'), os.W_OK)

    async def bulk_convert(self):
        """ Convert the temperature of all thermometers at once, the write returns after the conversion;
            the next read of a thermometer reads its value without another conversion
        """
        await asyncio.to_thread(_write_text, self._attribute('therm_bulk_read'), 'trigger\n')


def _read_text(path) -> str:
    with open(path, 'rb') as file:
        return file.read().decode()


def _write_text(path, text: str):
    """ One write of the text, an attribute takes one write """
    with open(path, 'wb', buffering=0) as file:
        file.write(text.encode())


def _read_byte(path) -> int:
    """ An attribute of one byte, the drivers of DS2408 and DS2413 refuse a read of more bytes """
    fd = os.open(path, os.O_RDONLY)
    try:
        data = os.read(fd, 1)
    finally:
        os.close(fd)
    if len(data) != 1:
        raise OSError(f"no state read from {path}")
    return data[0]


class W1Device:
    """ A slave in sysfs with the interface of the sensors: get(field), get_sensed_all()

        A failed read raises OSError, e.g. a CRC error or a device which does not answer.
    """

    def __init__(self, path: str):
        self.path = path
        self.family = int(os.path.basename(path)[:2], 16)

    async def _text(self, attribute) -> str:
        return (await asyncio.to_thread(_read_text, os.path.join(self.path, attribute))).strip()

    async def get(self, field: str) -> float:
        """ temperature in C; DS2438: VDD, VAD and vis in V """
        if self.family in THERMOMETERS and field == 'temperature':
            return int(await self._text('temperature')) / 1000
        if self.family == 0x26:
            if field == 'temperature':
                # the register in 1/256 C
                return int(await self._text('temperature')) / 256
            if field in ('VDD', 'VAD'):
                # the register in 10 mV
                return int(await self._text(field.lower())) / 100
            if field == 'vis':
                # the current register, the voltage of the sense resistor in 0.2441 mV
                return int(await self._text('iad')) * 0.0002441
        raise ValueError(f"1-Wire family {self.family:02X} has no value {field}")

    async def get_sensed_all(self) -> list[int]:
        """ The levels of the PIOs, the first one first """
        if self.family == 0x29:
            # the PIO logic state
            state = await asyncio.to_thread(_read_byte, os.path.join(self.path, 'state'))
            return [(state >> pio) & 1 for pio in range(8)]
        if self.family == 0x3A:
            # PIOA in bit 0, PIOB in bit 2, their output latches in bits 1 and 3
            state = await asyncio.to_thread(_read_byte, os.path.join(self.path, 'state'))
            return [state & 1, (state >> 2) & 1]
        if self.family == 0x12:
            # the kernel gives only the channel flip-flops of PIO-A and PIO-B, not the sensed levels
            state = await asyncio.to_thread(_read_byte, os.path.join(self.path, 'state'))
            return [state & 1, (state >> 1) & 1]
        raise ValueError(f"1-Wire family {self.family:02X} has no PIO")
