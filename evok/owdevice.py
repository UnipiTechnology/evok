import asyncio

from .devices import *
from .log import *

import anyio
from asyncowfs import OWFS
from asyncowfs import event

MAX_LOSTINTERVAL = 300  # 5 minutes

SUPPORTED_DEVICES = ["DS18S20", "DS18B20", "DS2438", "DS2408", "DS2413"]


class NotSupportedError(Exception):
    pass


class MySensor(object):
    def __init__(self, addr, sensor_type, bus, interval=None, dynamic=True, circuit=None, major_group=1, is_static=False):
        self.alias = ""
        self.devtype = SENSOR
        self.type = sensor_type
        self.circuit = circuit if circuit is not None else addr.replace('.', '')
        self.major_group = major_group
        self.address = addr
        self.interval = bus.interval if interval is None else interval  # seconds
        self.is_dynamic_interval = dynamic  # dynamically change interval #TODO
        self.last_value = None
        self.value = None
        self.lost = False
        self.time = 0
        self.readtime = 0
        self.sens = None
        if is_static:
            self.__bus = bus  # can't pickle, must be reset/set by pickling/un-pickling
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
            self.interval = int(interval)
            self.time = anyio.current_time() + self.calc_interval()
            devents.config(self)
        if alias is not None:
            Devices.set_alias(alias, self)

    async def read_val_from_sens(self, sens):
        raise NotImplementedError("Please Implement this method")

    def calc_interval(self):
        if self.lost:  # Sensor is inactive (disconnected)
            self.lostinterval *= 2
            if self.lostinterval > MAX_LOSTINTERVAL: self.lostinterval = MAX_LOSTINTERVAL
            return self.lostinterval
        if self.is_dynamic_interval:
            ##TODO
            pass
        return self.interval

    def set_lost(self):
        if self.lost: return
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

    def simple(self):
        ret = {'dev': 'temp',
               'circuit': self.circuit,
               'value': self.value,
               'lost': self.lost,
               'type': self.type}
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret

    async def read_val_from_sens(self, sens):
        new_val = float(await sens.get('temperature'))
        if not (new_val == 85.0 and abs(new_val - self.value) > 2):
            self.value = round(new_val * 2, 1) / 2  # 4 bits for frac part of number
            devents.status(self)
        else:
            logger.debug("PoR detected! 85C")


class DS2438(MySensor):  # vdd + vad + thermometer

    def full(self):
        self.value = (getattr(self, 'VDD', None), getattr(self, 'VAD', None), getattr(self, 'temperature', None),
                      getattr(self, 'IAD', None))
        ret = {'dev': '1wdevice',
               'circuit': self.circuit,
               # 'humidity1':(((((float(self.value[1]) / float(self.value[0])) - 0.1515)) / 0.00636) / (1.0546 - 0.00216 * float(self.value[2]))),
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

    def simple(self):
        ret = {'dev': '1wdevice',
               'circuit': self.circuit,
               'vdd': getattr(self, 'VDD', None),
               'vad': getattr(self, 'VAD', None),
               'temp': getattr(self, 'temperature', None),
               'vis': getattr(self, 'vis', None),
               'lost': self.lost,
               'type': self.type
               }
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret

    async def read_attribute(self, field):
        if type(field) is list:
            fname = '.'.join(field)
            setattr(self, fname, await self.sens.get(*field))
        else:
            setattr(self, field, await self.sens.get(field))

    async def read_val_from_sens(self, sens):
        async with anyio.create_task_group() as tg:
            for f in ('temperature', ['HIH4000', 'humidity'], 'VDD', 'VAD', 'vis'):
                tg.start_soon(self.read_attribute, f)
        # self.value = (sens.VDD, sens.VAD, sens.temperature, sens.vis)


class DS2408(MySensor):
    def __init__(self, addr, sensor_type, bus, interval=None, is_dynamic_interval=True, circuit=None, major_group=1,
                 is_static=False):
        self.type = sensor_type
        self.circuit = circuit if circuit != None else addr
        self.address = addr
        self.major_group = major_group
        self.interval = bus.interval if interval is None else interval  # seconds
        self.is_dynamic_interval = is_dynamic_interval  # dynamically change interval #TODO
        self.last_value = None
        self.value = None
        self.lost = False
        self.time = 0
        self.readtime = 0
        self.sens = None
        if is_static:
            self.__bus = bus  # can't pickle, must be reset/set  by pickeling/unpicklgin
        bus.register_sensor(self)
        self.pios = []

    async def read_val_from_sens(self, sens):
        # latch.0 sensed.0 PIO.0
        # actual values must be read from sensed_ALL, but writes to the GPIOs must be done in PIO_x(PIO_ALL)
        # pios_values = map(int, self.sens.sensed_ALL.split(','))
        value = await sens.get_sensed_all()
        # pios_values = [int(not int(i)) for i in self.sens.sensed_ALL.split(',')]
        if self.value != value:
            self.value = value
            devents.status(self)
            # update DS_2408_pio object that are attached to this DS2408
            if type(value) is list:
                pios_cnt = len(value)
                for pio in self.pios:
                    if pio.pin < pios_cnt:
                        pio.set_value(value[pio.pin])

    def full(self):
        ret = {'dev': '1wdevice',
               'circuit': self.circuit,
               'address': self.address,
               'value': None,
               'type': self.type
               }
        if self.alias is not None and self.alias != '':
            ret['alias'] = self.alias
        return ret

    def simple(self):
        return self.full()

    def m_set_pio(self, pio, value):
        self.__bus.taskWr.send((OWCMD_SET_PIO, self.circuit, value))

    def set_pio(self, pio, value):
        # elif command == OWCMD_SET_PIO:
        #    mysensor = next(x for x in self.mysensors if x.circuit == circuit)
        #    if mysensor:
        #        pin, value = value
        #        mysensor.set_pio(pin, int(value))

        if self.type == 'DS2408':
            setattr(self.sens, 'PIO_' + repr(pio), str(value))
        elif self.type == 'DS2406' or self.type == 'DS2413':
            pio_alpha = dict(zip(range(0, 26), string.ascii_uppercase))
            setattr(self.sens, 'PIO_' + pio_alpha[pio], str(value))

    def register_pio(self, pio):
        if not pio in self.pios:
            self.pios.append(pio)


def MySensorFabric(address, sensor_type, bus, interval=None, dynamic=True, circuit=None, major_group=1, is_static=False):
    if (sensor_type == 'DS18B20') or (sensor_type == 'DS18S20'):
        return DS18B20(address, sensor_type, bus, interval=interval, circuit=circuit)
    elif sensor_type == 'DS2438':
        return DS2438(address, sensor_type, bus, interval=interval, circuit=circuit)
    elif (sensor_type == 'DS2408') or (sensor_type == 'DS2406') or (sensor_type == 'DS2404') or (sensor_type == 'DS2413'):
        return DS2408(address, sensor_type, bus, interval=interval, circuit=circuit, is_static=is_static)
    else:
        logger.debug("Unsupported 1wire device %s (%s) detected", sensor_type, address)
        return None


class OwBusDriver:

    def __init__(self, circuit, interval=60, scan_interval=300, major_group=1,
                 owpower_circuit=None):
        self.bus_driver = self
        self.devtype = OWBUS
        self.circuit = circuit
        self.major_group = major_group
        self.scan_interval = scan_interval
        self.interval = interval
        self.scanned = set()
        self.mysensors = list()
        self.ow = None
        self.owpower_circuit = owpower_circuit

    def full(self):
        return {'dev': 'owbus',
                'circuit': self.circuit,
                'bus': 'OWFS',
                'scan_interval': self.scan_interval,
                'interval': self.interval,
                'do_scan': False,
                'do_reset': False}

    def list(self):
        list = dict()
        for dev in SUPPORTED_DEVICES:
            temp_list = [sens.address for sens in self.mysensors if sens.type == dev]
            list[dev] = temp_list
        return list

    def switch_to_async(self, mainLoop):
        mainLoop.add_callback(self.run)

    async def set(self, scan_interval=None, do_scan=False, interval=None, do_reset=None):
        was_changed = False

        if do_reset is not None:
            await self.do_reset()
        if not (scan_interval is None) and (scan_interval != self.scan_interval):
            self.scan_interval = scan_interval
            was_changed = True
        if do_scan:
            logger.info("Invoked scan of 1W bus")
            await self.do_scan(invoked_async=True)
        if not (interval is None) and (interval != self.interval):
            self.interval = interval
            for mysensor in self.mysensors:  # Global change - for all sensors
                mysensor.interval = interval
                mysensor.time = 0
            was_changed = True

        if was_changed:
            devents.config(self)
        return self.full()

    def register_sensor(self, mysensor):
        self.mysensors.append(mysensor)
        Devices.register_device(SENSOR, mysensor)

    def do_scan(self, invoked_async=False):
        if hasattr(self, 'scanning_scope'):
            self.scanning_scope.cancel()

    async def do_reset(self):
        if self.owpower_circuit is not None:
            logger.info("Invoked reset of 1W master")
            owpower = Devices.by_int(OWPOWER, self.owpower_circuit)
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
            # if self.scan_interval > 0:
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
                await anyio.sleep(self.interval if self.interval > 0 else 5)
                continue
            # Find sensor with min time (all se to 0 as default)
            mysensor = min(self.mysensors, key=lambda x: x.time)
            t1 = anyio.current_time()
            if t1 < mysensor.time:
                await anyio.sleep(mysensor.time - t1)
                continue

            try:
                # Read values from selected sensor
                async with self.bus_lock:
                    await mysensor.read_val_from_sens(mysensor.sens)
                # Store last read time
                mysensor.lost = False
                mysensor.readtime = t1
            except Exception:
                if not mysensor.lost:  # Catch the edge
                    mysensor.set_lost()
            mysensor.time = anyio.current_time() + mysensor.calc_interval()

    async def mon(self, ow):
        async with ow.events as events:
            async for msg in events:
                logger.info("%s", msg)
                if isinstance(msg, event.DeviceLocated):
                    # for f in msg.device.fields:print(f)
                    sensor_type = await msg.device.get_type()
                    address = msg.device.id
                    try:
                        mysensor = next(x for x in self.mysensors if x.address == address)
                        logger.info("Sensor found " + str(mysensor.circuit))
                    except Exception:
                        mysensor = MySensorFabric(address, sensor_type, self, self.interval)
                    if mysensor:
                        mysensor.sens = msg.device
                        mysensor.lost = False
                        mysensor.time = 0

                elif isinstance(msg, event.DeviceNotFound):
                    address = msg.device.id
                    try:
                        mysensor = next(x for x in self.mysensors if x.address == address)
                        logger.info(f"Sensor {address} disappeared")
                        mysensor.sens = None
                        mysensor.set_lost()
                    except Exception:
                        pass

    async def run(self):
        self.bus_lock = anyio.Lock()
        async with OWFS(initial_scan=False) as ow:
            await ow.add_task(self.mon, ow)
            server = await ow.add_server('127.0.0.1', 4304)  # host, port)
            await ow.add_task(self.scanning, server)
            await self.poll()
