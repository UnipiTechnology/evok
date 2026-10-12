""" The 1-Wire bus: the sensors found by the kernel, the poll of their values """
import asyncio
import typing

from ..devices import OWBUS, OWPOWER
from ..devices import devents, Devices, SENSOR, to_bool
from ..log import logger
from ..modbus import set_devices
from . import sysfs
from .sysfs import address_key
from .sensors import SUPPORTED_DEVICES, DuplicateCircuitError, MySensorFabric, NotSupportedError, check_interval

RECONNECT_DELAY = 10  # s, the next attempt to use the 1-Wire master after a failure


def leaf_error(error: BaseException) -> BaseException:
    """ The first error in the nested exception groups of a task group and the cause of an OSError
    """
    while True:
        if isinstance(error, BaseExceptionGroup) and error.exceptions:
            error = error.exceptions[0]
        elif isinstance(error, OSError) and error.__cause__ is not None:
            error = error.__cause__
        else:
            return error


class OwBusDriver:

    def __init__(self, circuit, interval=60, scan_interval=300, major_group=1,
                 owpower_circuit=None, master=None):
        """ master is the name of the 1-Wire master of the kernel, the first one by default """
        self.bus_driver = self
        self.master = master
        self.master_name = master       # the used master, also the first one found
        self.devtype = OWBUS
        self.circuit = circuit
        self.major_group = major_group
        # scan_interval 0 scans only after the connection and on request (do_scan)
        self.scan_interval = check_interval(scan_interval, 'scan_interval', zero=True)
        self.interval = check_interval(interval)
        self.scanned = set()
        self.mysensors = list()
        self.owpower_circuit = owpower_circuit
        self._wakeup = None     # the event waking up poll()
        self._scan_wakeup = None    # the event waking up scanning()
        self._scan_requested = False
        self._logged_error = None   # (type, text) of the logged failure, the same one is not logged again
        self._skipped = set()       # the address keys of the found sensors not created, logged once

    def full(self):
        return {'dev': 'owbus',
                'circuit': self.circuit,
                'bus': 'OWFS',
                'master': self.master_name,
                'scan_interval': self.scan_interval,
                'interval': self.interval,
                'do_scan': False,
                'do_reset': False}

    def list(self):
        """ Addresses of the sensors on the bus by their type, used in RPC """
        return {sensor_type: [sens.address for sens in self.mysensors if sens.type == sensor_type]
                for sensor_type in SUPPORTED_DEVICES}

    def start_scanning(self):
        self._run_task = asyncio.create_task(self.run_forever())

    async def run_forever(self):
        """ Run the bus, use the master again after a failure, e.g. its driver was not loaded """
        while True:
            try:
                await self.run()
            except asyncio.CancelledError:
                raise
            except Exception as E:
                self._log_failure(E)
            # the devices are located again by the next scan
            for mysensor in self.mysensors:
                mysensor.sens = None
                mysensor.set_lost()
            await asyncio.sleep(RECONNECT_DELAY)

    def _log_failure(self, error):
        """ Log the reason of the failure once until the next start, it was an ExceptionGroup of the task group """
        error = leaf_error(error)
        if isinstance(error, OSError):
            message = (f"1-Wire bus {self.circuit}: cannot use the 1-Wire master, is its driver loaded "
                       f"(e.g. ds2482)? {type(error).__name__}: {error}")
        else:
            message = f"1-Wire bus {self.circuit} failed: {type(error).__name__}: {error}"
        kind = (type(error), str(error))
        if kind != self._logged_error:
            self._logged_error = kind
            logger.error(f"{message}; trying again every {RECONNECT_DELAY} s, the next errors are not logged")
        else:
            logger.debug(message)

    def _log_connected(self):
        """ The master found ends a missing master, another failure of the bus repeats after every start,
            it is logged once
        """
        message = f"1-Wire bus {self.circuit} uses the master {self.master_name}"
        if self._logged_error is None or issubclass(self._logged_error[0], OSError):
            self._logged_error = None
            logger.info(message)
        else:
            logger.debug(message)

    async def set(self, scan_interval=None, do_scan=False, interval=None, do_reset=None):
        was_changed = False

        if scan_interval is not None:
            scan_interval = check_interval(scan_interval, 'scan_interval', zero=True)
        if interval is not None:
            interval = check_interval(interval)
        do_scan = do_scan is not None and to_bool(do_scan)
        do_reset = do_reset is not None and to_bool(do_reset)

        if do_reset:
            await self.do_reset()
        if not (scan_interval is None) and (scan_interval != self.scan_interval):
            self.scan_interval = scan_interval
            # the new interval applies at once, not after the current one, with 0 it was an hour
            self._wake_scanning()
            was_changed = True
        if do_scan:
            logger.info("Invoked scan of 1W bus")
            self.do_scan()
        if not (interval is None) and (interval != self.interval):
            self.interval = interval
            for mysensor in self.mysensors:  # Global change - for all sensors
                mysensor.interval = interval
                mysensor.time = 0
            self.wake()
            was_changed = True

        if was_changed:
            # the clients of WebSocket get the new state
            devents.status(self)

    def register_sensor(self, mysensor):
        """ A circuit of a sensor of any OWFS bus raises DuplicateCircuitError """
        other = Devices[SENSOR].get(str(mysensor.circuit))
        if other is not None:
            raise DuplicateCircuitError(f"1-Wire sensor '{mysensor.circuit}' ({mysensor.address}) of bus "
                                        f"'{self.circuit}' has the same name as the sensor {other.address} "
                                        f"of bus '{other.bus.circuit}'")
        self.mysensors.append(mysensor)
        Devices.register_device(SENSOR, mysensor)
        self.wake()

    def wake(self):
        """ Wake up poll() sleeping until the next read, a sensor was added or its time was changed """
        if self._wakeup is not None:
            self._wakeup.set()

    async def _sleep(self, delay):
        """ Sleep until the delay passes or wake() is called """
        self._wakeup = asyncio.Event()
        try:
            async with asyncio.timeout(delay):
                await self._wakeup.wait()
        except TimeoutError:
            pass
        finally:
            self._wakeup = None

    def _find_sensor(self, address):
        key = address_key(address)
        return next((x for x in self.mysensors if address_key(x.address) == key), None)

    def do_scan(self):
        """ Read the sensors found by the kernel at once, the kernel searches the bus every 10 s """
        self._scan_requested = True
        self._wake_scanning()

    def _wake_scanning(self):
        if self._scan_wakeup is not None:
            self._scan_wakeup.set()

    async def do_reset(self):
        if self.owpower_circuit is not None:
            logger.info("Invoked reset of 1W master")
            owpower = Devices.by_name(OWPOWER, self.owpower_circuit)
            # under the lock of its Modbus unit, its state and event follow the writes
            await set_devices([(owpower, dict(value=True))])
            await asyncio.sleep(0.2)
            await set_devices([(owpower, dict(value=False))])
            await asyncio.sleep(0.05)
            self.do_scan()
        else:
            raise NotSupportedError("1W reset is not supported on this device!")

    # Running async tasks: scanning, poll
    async def scanning(self, master: sysfs.W1Master):
        """ Take the sensors found by the kernel after the start, then every scan_interval, with 0 only on request """
        while True:
            # a request during the scan scans again
            self._scan_requested = False
            # a failure of the master ends the bus, it is used again after RECONNECT_DELAY
            self._update(master, await master.slaves())
            await self._wait_for_scan()

    def _update(self, master: sysfs.W1Master, names: "typing.List[str]"):
        """ Assign the found devices to the sensors, create the found ones, a sensor not found is lost """
        found = {address_key(name): name for name in names}
        for key, name in found.items():
            mysensor = self._find_sensor(key)
            if mysensor is None:
                mysensor = self._create_found(sysfs.owfs_address(name), sysfs.FAMILY_TYPES.get(int(name[:2], 16)))
            elif mysensor.sens is None:
                logger.info(f"Sensor {mysensor.circuit} found")
            if mysensor is not None and mysensor.sens is None:
                # read at once, poll() reports the recovery of a lost sensor
                mysensor.sens = master.device(name)
                mysensor.time = 0
                self.wake()
        for mysensor in self.mysensors:
            if address_key(mysensor.address) in found:
                continue
            if mysensor.sens is not None:
                logger.info(f"Sensor {mysensor.circuit} ({mysensor.address}) disappeared")
            elif not mysensor.lost:
                logger.info(f"Sensor {mysensor.circuit} ({mysensor.address}) not found on the bus")
            mysensor.sens = None
            mysensor.set_lost()

    async def _wait_for_scan(self):
        """ Wait for scan_interval or do_scan(), a change of scan_interval starts the wait again """
        while not self._scan_requested:
            self._scan_wakeup = asyncio.Event()
            try:
                # scan_interval 0 waits only for do_scan()
                async with asyncio.timeout(self.scan_interval or None):
                    await self._scan_wakeup.wait()
            except TimeoutError:
                return
            finally:
                self._scan_wakeup = None

    async def poll(self):
        """
            Peridocally poll 1wire sensors, else sleep
        """

        while True:
            # a sensor without its device is not found yet or disappeared, its read failed
            # and reported it lost at the start; the scan wakes poll() when it is found
            located = [x for x in self.mysensors if x.sens is not None]
            if not located:
                await self._sleep(self.interval)
                continue
            # Find sensor with min time (all se to 0 as default)
            mysensor = min(located, key=lambda x: x.time)
            t1 = asyncio.get_running_loop().time()
            if t1 < mysensor.time:
                await self._sleep(mysensor.time - t1)
                continue
            await self.read_sensor(mysensor, t1)
            mysensor.time = asyncio.get_running_loop().time() + mysensor.calc_interval()

    async def read_sensor(self, mysensor, now):
        """ Read the sensor, report a change of its values and its recovery or loss """
        try:
            async with self.bus_lock:
                changed = await mysensor.read_val_from_sens(mysensor.sens)
        except Exception as E:
            if not mysensor.lost:  # Catch the edge
                logger.debug(f"Sensor {mysensor.circuit} is lost: {type(E).__name__}: {E}")
                mysensor.set_lost()
            return
        was_lost = mysensor.lost
        mysensor.lost = False
        mysensor.readtime = now
        if changed or was_lost:
            devents.status(mysensor)

    def _create_found(self, address, sensor_type):
        """ Create a found sensor; an unsupported one and one with the circuit of a created sensor
            are skipped, logged once, the kernel lists them after every search
        """
        key = address_key(address)
        if key in self._skipped:
            return None
        try:
            mysensor = MySensorFabric(address, sensor_type, self, self.interval)
        except DuplicateCircuitError as E:
            self._skipped.add(key)
            logger.warning(f"{E}, the found sensor is skipped")
            return None
        if mysensor is None:
            self._skipped.add(key)
        else:
            logger.info(f"New sensor {sensor_type} {address} found")
        return mysensor

    async def run(self):
        """ Scan and poll the bus of the master, a missing master raises FileNotFoundError """
        self.bus_lock = asyncio.Lock()
        master = sysfs.W1Master(self.master)
        self.master_name = master.name
        self._log_connected()
        # a failure of the scan cancels the poll
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self.scanning(master))
            await self.poll()
