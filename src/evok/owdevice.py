import asyncio
import math
import typing

from .devices import SENSOR, OWBUS, OWPOWER
from .devices import devents, Devices, to_bool  # noqa: F401, to_bool is used also by tests
from .log import logger
from .modbus import set_devices
from . import w1
from .w1 import address_key  # noqa: F401, used also by tests

import anyio

MAX_LOSTINTERVAL = 300  # 5 minutes
RECONNECT_DELAY = 10  # s, the next attempt to use the 1-Wire master after a failure


def leaf_error(error: BaseException) -> BaseException:
    """ The first error in the nested exception groups of anyio and the cause of an OSError
    """
    while True:
        if isinstance(error, BaseExceptionGroup) and error.exceptions:
            error = error.exceptions[0]
        elif isinstance(error, OSError) and error.__cause__ is not None:
            error = error.__cause__
        else:
            return error


def check_interval(interval, name='interval', zero=False):
    """ An interval in seconds, 0 or negative interval would poll the bus continuously """
    interval = int(float(interval))
    if interval < 0 or (interval == 0 and not zero):
        raise ValueError(f"Invalid {name} {interval}, it must be {'0 or ' if zero else ''}a positive number")
    return interval


# the sensor types created by MySensorFabric, DS2404 has no PIO, its read always failed
SUPPORTED_DEVICES = ["DS18S20", "DS18B20", "DS2438", "DS2408", "DS2406", "DS2413"]


class NotSupportedError(ValueError):
    """ The request is not supported by the device, a ValueError is reported as a bad request """
    pass


class DuplicateCircuitError(ValueError):
    """ A sensor with the circuit of a created one, it replaced the created sensor in Devices """
    pass


class MySensor(object):
    def __init__(self, addr, sensor_type, bus, interval=None, circuit=None, major_group=1):
        self.alias = ""
        self.devtype = SENSOR
        self.type = sensor_type
        self.circuit = circuit if circuit is not None else addr.replace('.', '')
        self.major_group = major_group
        self.address = addr
        self.interval = bus.interval if interval is None else check_interval(interval)  # seconds
        self.value = None
        self.lost = False
        self.time = 0
        self.readtime = 0
        self.sens = None
        self.bus = bus
        bus.register_sensor(self)

    def get_value(self):
        ''' Get live value from sensor
            used in rpc only
        '''
        return self.value

    def get(self):
        ''' Get live data from sensor without names
            used in rpc only
        '''
        return self.value, self.lost, self.readtime, self.interval

    async def set(self, interval=None, alias=None):
        if interval is not None:
            self.interval = check_interval(interval)
            self.time = anyio.current_time() + self.calc_interval()
            self.bus.wake()
        if alias is not None:
            Devices.set_alias(alias, self)
        if interval is not None or alias is not None:
            # the clients of WebSocket get the new state
            devents.status(self)

    async def read_val_from_sens(self, sens) -> bool:
        """ Read the values, return True if they have changed, the change is reported by poll() """
        raise NotImplementedError("Please Implement this method")

    def calc_interval(self):
        if self.lost:  # Sensor is inactive (disconnected)
            self.lostinterval *= 2
            if self.lostinterval > MAX_LOSTINTERVAL:
                self.lostinterval = MAX_LOSTINTERVAL
            return self.lostinterval
        return self.interval

    def set_lost(self):
        if self.lost:
            return
        self.lost = True
        self.lostinterval = self.interval
        devents.status(self)


class DS18B20(MySensor):  # thermometer
    def full(self):
        ret = {'dev': 'temp',
               'circuit': self.circuit,
               'address': self.address,
               'value': self.value,
               'lost': self.lost,
               'time': self.readtime,
               'interval': self.interval,
               'type': self.type,
               }
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret

    por_skipped = False     # the last value was skipped as the power-on reset value

    async def read_val_from_sens(self, sens) -> bool:
        new_val = float(await sens.get('temperature'))
        # 85 C is the value after power-on reset, it is skipped once if it is the first one or a jump
        if new_val == 85.0 and not self.por_skipped and (self.value is None or abs(new_val - self.value) > 2):
            self.por_skipped = True
            logger.debug("PoR detected! 85C")
            return False
        self.por_skipped = False
        old_value = self.value
        self.value = round(new_val * 2, 1) / 2  # 4 bits for frac part of number
        return self.value != old_value


class DS2438(MySensor):  # vdd + vad + thermometer

    FIELDS = ('temperature', 'HIH4000.humidity', 'VDD', 'VAD', 'vis')

    def full(self):
        ret = {'dev': '1wdevice',
               'circuit': self.circuit,
               'humidity': getattr(self, 'HIH4000.humidity', None),
               'vdd': getattr(self, 'VDD', None),
               'vad': getattr(self, 'VAD', None),
               'temp': getattr(self, 'temperature', None),
               'vis': getattr(self, 'vis', None),
               'lost': self.lost,
               'time': self.readtime,
               'interval': self.interval,
               'type': self.type
               }
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret

    def _values(self):
        return {name: getattr(self, name, None) for name in self.FIELDS}

    @staticmethod
    def hih4000_humidity(vad, vdd, temperature) -> float | None:
        """ The relative humidity of a HIH4000 at VAD, computed as by owfs """
        if not vdd:
            return None
        return round((vad / vdd - 0.16) / (0.0062 * (1.0546 - 0.00216 * temperature)), 2)

    async def read_val_from_sens(self, sens) -> bool:
        """ The reads of a device are serialized by the kernel, they are done one after another """
        old_values = self._values()
        values = {field: await sens.get(field) for field in ('temperature', 'VDD', 'VAD', 'vis')}
        values['HIH4000.humidity'] = self.hih4000_humidity(values['VAD'], values['VDD'], values['temperature'])
        for field, value in values.items():
            setattr(self, field, value)
        # the value used by get() and get_value() in RPC
        self.value = (getattr(self, 'VDD', None), getattr(self, 'VAD', None), getattr(self, 'temperature', None),
                      getattr(self, 'IAD', None))
        return self._values() != old_values


class DS2408(MySensor):
    def __init__(self, addr, sensor_type, bus, interval=None, circuit=None, major_group=1):
        # the circuit of a found DS2408 is its address with the dot, unlike the other sensors
        super().__init__(addr, sensor_type, bus, interval=interval,
                         circuit=circuit if circuit is not None else addr, major_group=major_group)

    async def read_val_from_sens(self, sens) -> bool:
        # the actual values of the PIOs are in sensed_ALL
        value = await sens.get_sensed_all()
        if self.value == value:
            return False
        self.value = value
        return True

    def full(self):
        ret = {'dev': '1wdevice',
               'circuit': self.circuit,
               'address': self.address,
               'value': self.value,
               'lost': self.lost,
               'time': self.readtime,
               'interval': self.interval,
               'type': self.type
               }
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret


def MySensorFabric(address, sensor_type, bus, interval=None, circuit=None):
    if (sensor_type == 'DS18B20') or (sensor_type == 'DS18S20'):
        return DS18B20(address, sensor_type, bus, interval=interval, circuit=circuit)
    elif sensor_type == 'DS2438':
        return DS2438(address, sensor_type, bus, interval=interval, circuit=circuit)
    elif sensor_type in ('DS2408', 'DS2406', 'DS2413'):
        return DS2408(address, sensor_type, bus, interval=interval, circuit=circuit)
    else:
        logger.info("Unsupported 1wire device %s (%s) detected", sensor_type, address)
        return None


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
        """ Log the reason of the failure once until the next connection, it was an ExceptionGroup of anyio """
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
        self._wakeup = anyio.Event()
        with anyio.move_on_after(delay):
            await self._wakeup.wait()
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
    async def scanning(self, master: w1.W1Master):
        """ Take the sensors found by the kernel after the start, then every scan_interval, with 0 only on request """
        while True:
            # a request during the scan scans again
            self._scan_requested = False
            # a failure of the master ends the bus, it is used again after RECONNECT_DELAY
            self._update(master, await master.slaves())
            await self._wait_for_scan()

    def _update(self, master: w1.W1Master, names: "typing.List[str]"):
        """ Assign the found devices to the sensors, create the found ones, a sensor not found is lost """
        found = {address_key(name): name for name in names}
        for key, name in found.items():
            mysensor = self._find_sensor(key)
            if mysensor is None:
                mysensor = self._create_found(w1.owfs_address(name), w1.FAMILY_TYPES.get(int(name[:2], 16)))
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
            self._scan_wakeup = anyio.Event()
            try:
                with anyio.move_on_after(self.scan_interval or math.inf) as scope:
                    await self._scan_wakeup.wait()
            finally:
                self._scan_wakeup = None
            if scope.cancelled_caught:
                return

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
            t1 = anyio.current_time()
            if t1 < mysensor.time:
                await self._sleep(mysensor.time - t1)
                continue
            await self.read_sensor(mysensor, t1)
            mysensor.time = anyio.current_time() + mysensor.calc_interval()

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
        self.bus_lock = anyio.Lock()
        master = w1.W1Master(self.master)
        self.master_name = master.name
        self._log_connected()
        async with anyio.create_task_group() as tg:
            tg.start_soon(self.scanning, master)
            await self.poll()
