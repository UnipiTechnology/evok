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


@pytest.mark.parametrize('interval', [0, -5, '0', 'x'])
async def test_invalid_interval(bus, interval):
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    with pytest.raises(ValueError):
        await sensor.set(interval=interval)
    with pytest.raises(ValueError):
        await bus.set(interval=interval)
    with pytest.raises(ValueError):
        OwBusDriver('OW2', interval=interval)
    with pytest.raises(ValueError):
        DS18B20('28.000002', 'DS18B20', bus, interval=interval)
    assert (sensor.interval, bus.interval) == (10, 10)


async def test_scan_interval(bus):
    await bus.set(scan_interval='0')            # scan only on request
    assert bus.scan_interval == 0
    with pytest.raises(ValueError):
        await bus.set(scan_interval=-1)


async def test_reconnect_after_failure(bus, events, monkeypatch, caplog):
    import asyncio
    from evok import owdevice
    monkeypatch.setattr(owdevice, 'RECONNECT_DELAY', 0)
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    sensor.sens = FakeSens(temperature=21.0)
    runs = []

    async def run():
        runs.append(None)
        if len(runs) < 3:
            raise ConnectionRefusedError('owserver is not running')
        await asyncio.Event().wait()
    monkeypatch.setattr(bus, 'run', run)
    bus.switch_to_async()
    for _ in range(100):
        if len(runs) == 3:
            break
        await asyncio.sleep(0)
    bus._run_task.cancel()
    assert len(runs) == 3
    assert (sensor.sens, sensor.lost) == (None, True)
    assert events == [sensor]                   # the loss is reported once
    assert caplog.text.count('connecting again') == 2
