import asyncio

from .devices import SENSOR, OWBUS, OWPOWER
from .devices import devents, Devices, to_bool  # noqa: F401, to_bool is used also by tests
from .log import logger

import anyio
from asyncowfs import OWFS
from asyncowfs import event

MAX_LOSTINTERVAL = 300  # 5 minutes
RECONNECT_DELAY = 10  # s, the next connection to owserver after a failure


def check_interval(interval, name='interval', zero=False):
    """ An interval in seconds, 0 or negative interval would poll the bus continuously """
    interval = int(float(interval))
    if interval < 0 or (interval == 0 and not zero):
        raise ValueError(f"Invalid {name} {interval}, it must be {'0 or ' if zero else ''}a positive number")
    return interval

# the sensor types created by MySensorFabric
SUPPORTED_DEVICES = ["DS18S20", "DS18B20", "DS2438", "DS2408", "DS2406", "DS2404", "DS2413"]


class NotSupportedError(ValueError):
    """ The request is not supported by the device, a ValueError is reported as a bad request """
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

    async def read_attribute(self, sens, field):
        if type(field) is list:
            fname = '.'.join(field)
            setattr(self, fname, await sens.get(*field))
        else:
            setattr(self, field, await sens.get(field))

    def _values(self):
        return {name: getattr(self, name, None) for name in self.FIELDS}

    async def read_val_from_sens(self, sens) -> bool:
        old_values = self._values()
        async with anyio.create_task_group() as tg:
            for f in ('temperature', ['HIH4000', 'humidity'], 'VDD', 'VAD', 'vis'):
                tg.start_soon(self.read_attribute, sens, f)
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
    elif sensor_type in ('DS2408', 'DS2406', 'DS2404', 'DS2413'):
        return DS2408(address, sensor_type, bus, interval=interval, circuit=circuit)
    else:
        logger.info("Unsupported 1wire device %s (%s) detected", sensor_type, address)
        return None


class OwBusDriver:

    def __init__(self, circuit, interval=60, scan_interval=300, major_group=1,
                 owpower_circuit=None):
        self.bus_driver = self
        self.devtype = OWBUS
        self.circuit = circuit
        self.major_group = major_group
        # scan_interval 0 scans only on request (do_scan), in fact once per hour
        self.scan_interval = check_interval(scan_interval, 'scan_interval', zero=True)
        self.interval = check_interval(interval)
        self.scanned = set()
        self.mysensors = list()
        self.ow = None
        self.owpower_circuit = owpower_circuit
        self._wakeup = None     # the event waking up poll()

    def full(self):
        return {'dev': 'owbus',
                'circuit': self.circuit,
                'bus': 'OWFS',
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
        """ Run the bus, connect to owserver again after a failure """
        while True:
            try:
                await self.run()
            except asyncio.CancelledError:
                raise
            except Exception as E:
                logger.error(f"1-Wire bus {self.circuit} failed, connecting again in {RECONNECT_DELAY} s: "
                             f"{type(E).__name__}: {E}")
            # the devices are located again after the connection
            for mysensor in self.mysensors:
                mysensor.sens = None
                mysensor.set_lost()
            await asyncio.sleep(RECONNECT_DELAY)

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

    def do_scan(self):
        if hasattr(self, 'scanning_scope'):
            self.scanning_scope.cancel()

    async def do_reset(self):
        if self.owpower_circuit is not None:
            logger.info("Invoked reset of 1W master")
            owpower = Devices.by_name(OWPOWER, self.owpower_circuit)
            await owpower.set(value=True)
            await asyncio.sleep(0.2)
            await owpower.set(value=False)
            await asyncio.sleep(0.05)
            self.do_scan()
        else:
            raise NotSupportedError("1W reset is not supported on this device!")

    # Running async tasks: scanning, poll, mon
    async def scanning(self, server):
        while True:
            async with self.bus_lock:
                try:
                    await server.scan_now(polling=False)
                except Exception as E:
                    logger.error(f"{type(E)}: {str(E)}")
            with anyio.CancelScope() as scope:
                self.scanning_scope = scope
                await anyio.sleep(self.scan_interval if self.scan_interval > 0 else 3600)
            delattr(self, 'scanning_scope')

    async def poll(self):
        """
            Peridocally poll 1wire sensors, else sleep
        """

        while True:
            if not self.mysensors:
                await self._sleep(self.interval)
                continue
            # Find sensor with min time (all se to 0 as default)
            mysensor = min(self.mysensors, key=lambda x: x.time)
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

    async def mon(self, ow):
        async with ow.events as events:
            async for msg in events:
                logger.debug("%s", msg)
                if isinstance(msg, event.DeviceLocated):
                    sensor_type = await msg.device.get_type()
                    address = msg.device.id
                    mysensor = next((x for x in self.mysensors if x.address == address), None)
                    if mysensor is not None:
                        logger.info(f"Sensor {mysensor.circuit} found")
                    else:
                        mysensor = MySensorFabric(address, sensor_type, self, self.interval)
                        if mysensor is not None:
                            logger.info(f"New sensor {sensor_type} {address} found")
                    if mysensor:
                        # read at once, poll() reports the recovery of a lost sensor
                        mysensor.sens = msg.device
                        mysensor.time = 0
                        self.wake()

                elif isinstance(msg, event.DeviceNotFound):
                    address = msg.device.id
                    mysensor = next((x for x in self.mysensors if x.address == address), None)
                    if mysensor is not None:
                        logger.info(f"Sensor {address} disappeared")
                        mysensor.sens = None
                        mysensor.set_lost()

    async def run(self):
        self.bus_lock = anyio.Lock()
        async with OWFS(initial_scan=False) as ow:
            await ow.add_task(self.mon, ow)
            server = await ow.add_server('127.0.0.1', 4304)  # host, port)
            await ow.add_task(self.scanning, server)
            await self.poll()
