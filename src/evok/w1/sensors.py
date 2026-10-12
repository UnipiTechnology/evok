""" The 1-Wire sensors, their values are read from the devices of the bus """
import asyncio

from ..devices import SENSOR
from ..devices import devents, Devices
from ..log import logger

MAX_LOSTINTERVAL = 300  # 5 minutes


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
            self.time = asyncio.get_running_loop().time() + self.calc_interval()
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
