import json

import pytest

from evok import devents
from evok.devices import Devices, SENSOR
from evok.owdevice import DS18B20, DS2408, DS2438, OwBusDriver, MySensorFabric


@pytest.fixture
def events(monkeypatch):
    sent = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: sent.append(device))
    return sent


@pytest.fixture
def bus():
    return OwBusDriver('OW', interval=10)


class FakeSens:
    """ An asyncowfs device returning the given fields """
    def __init__(self, **fields):
        self.fields = fields

    async def get(self, *field):
        return self.fields['.'.join(field)]

    async def get_sensed_all(self):
        return self.fields['sensed_all']


@pytest.mark.parametrize('reads, expected', [
    ([85.0], None),                     # the first value after power-on reset is skipped
    ([85.0, 85.0], 85.0),               # a real 85 C is accepted next time
    ([85.0, 21.5], 21.5),
    ([21.5, 85.0], 21.5),               # a jump to 85 C is skipped
    ([84.0, 85.0], 85.0),               # no jump
])
async def test_ds18b20_power_on_reset(bus, events, reads, expected):
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    for value in reads:
        await sensor.read_val_from_sens(FakeSens(temperature=value))
    assert sensor.value == expected


async def test_ds2438_reports_changes(bus, events):
    sensor = DS2438('26.000001', 'DS2438', bus)
    sens = FakeSens(**{'temperature': 21.0, 'HIH4000.humidity': 40.0, 'VDD': 5.0, 'VAD': 2.0, 'vis': 0.1})
    await sensor.read_val_from_sens(sens)
    assert events == [sensor]
    assert sensor.get_value() == (5.0, 2.0, 21.0, None)
    await sensor.read_val_from_sens(sens)
    assert events == [sensor]                           # no change, no event
    sens.fields['temperature'] = 22.0
    await sensor.read_val_from_sens(sens)
    assert events == [sensor, sensor]
    assert sensor.full()['temp'] == 22.0
    assert sensor.full()['humidity'] == 40.0


@pytest.mark.parametrize('sensor_type', ['DS2408', 'DS2406', 'DS2413'])
async def test_ds2408(bus, events, sensor_type):
    sensor = MySensorFabric('29.000001', sensor_type, bus)
    assert isinstance(sensor, DS2408)
    assert (sensor.devtype, sensor.alias, sensor.circuit) == (SENSOR, '', '29.000001')
    assert Devices[SENSOR]['29.000001'] is sensor
    await sensor.read_val_from_sens(FakeSens(sensed_all=[0, 1, 0, 0]))
    state = json.loads(json.dumps(sensor.full()))
    assert state['value'] == [0, 1, 0, 0]
    assert events == [sensor]
    Devices.set_alias('gpio', sensor)
    assert Devices.by_name(SENSOR, 'gpio') is sensor
    assert sensor.full()['alias'] == 'gpio'
