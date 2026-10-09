import asyncio
import json

import anyio
import pytest

from evok import devents
from evok.devices import Devices, SENSOR
from evok.owdevice import DS18B20, DS2408, DS2438, OwBusDriver, MySensorFabric, address_key


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


async def read(bus, sensor):
    """ One read of the sensor by poll() """
    bus.bus_lock = anyio.Lock()
    await bus.read_sensor(sensor, anyio.current_time())


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
    sensor.sens = FakeSens(**{'temperature': 21.0, 'HIH4000.humidity': 40.0, 'VDD': 5.0, 'VAD': 2.0, 'vis': 0.1})
    await read(bus, sensor)
    assert events == [sensor]
    assert sensor.get_value() == (5.0, 2.0, 21.0, None)
    await read(bus, sensor)
    assert events == [sensor]                           # no change, no event
    sensor.sens.fields['temperature'] = 22.0
    await read(bus, sensor)
    assert events == [sensor, sensor]
    assert sensor.full()['temp'] == 22.0
    assert sensor.full()['humidity'] == 40.0


@pytest.mark.parametrize('sensor_type', ['DS2408', 'DS2406', 'DS2413'])
async def test_ds2408(bus, events, sensor_type):
    sensor = MySensorFabric('29.000001', sensor_type, bus)
    assert isinstance(sensor, DS2408)
    assert (sensor.devtype, sensor.alias, sensor.circuit) == (SENSOR, '', '29.000001')
    assert Devices[SENSOR]['29.000001'] is sensor
    sensor.sens = FakeSens(sensed_all=[0, 1, 0, 0])
    await read(bus, sensor)
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


async def test_set_sends_status(bus, events):
    """ The change was sent as a config event, which has no receiver """
    await bus.set(scan_interval=120)
    assert events == [bus]
    await bus.set(scan_interval=120)                            # no change, no event
    assert events == [bus]


async def test_sensor_set_sends_status(bus, events):
    """ The change of interval was sent as a config event, which has no receiver """
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    events.clear()
    await sensor.set(interval=30)
    await sensor.set(alias='outdoor')
    assert events == [sensor, sensor]
    await sensor.set()                                          # nothing set, no event
    assert len(events) == 2


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
    bus.start_scanning()
    for _ in range(100):
        if len(runs) == 3:
            break
        await asyncio.sleep(0)
    bus._run_task.cancel()
    assert len(runs) == 3
    assert (sensor.sens, sensor.lost) == (None, True)
    assert events == [sensor]                   # the loss is reported once
    assert caplog.text.count('connecting again') == 2


async def test_ds18b20_reports_only_changes(bus, events):
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    sensor.sens = FakeSens(temperature=21.5)
    await read(bus, sensor)
    await read(bus, sensor)
    assert events == [sensor]
    sensor.sens.fields['temperature'] = 22.0
    await read(bus, sensor)
    assert events == [sensor, sensor]


async def test_lost_and_recovered_sensor_is_reported(bus, monkeypatch):
    states = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: states.append(device.full()['lost']))
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    sensor.sens = FakeSens(temperature=21.5)
    await read(bus, sensor)
    sensor.sens = None                                  # the read fails
    await read(bus, sensor)
    await read(bus, sensor)
    assert sensor.lost
    sensor.sens = FakeSens(temperature=21.5)            # the same value after the recovery
    await read(bus, sensor)
    assert not sensor.lost
    assert states == [False, True, False]


async def test_poll_wakes_up_for_a_new_sensor(bus, events):
    bus.bus_lock = anyio.Lock()
    first = DS18B20('28.000001', 'DS18B20', bus)
    first.sens = FakeSens(temperature=21.5)
    task = asyncio.create_task(bus.poll())
    for _ in range(10):
        await asyncio.sleep(0)
    assert first.value == 21.5                          # read at once, the next read in 10 s
    second = DS18B20('28.000002', 'DS18B20', bus)
    second.sens = FakeSens(temperature=30.0)
    for _ in range(10):
        await asyncio.sleep(0)
    task.cancel()
    assert second.value == 30.0                         # not after 10 s


async def test_reset_without_owpower_is_a_bad_request(bus):
    with pytest.raises(ValueError, match='not supported'):
        await bus.set(do_reset=True)


def test_list(bus):
    DS18B20('28.000001', 'DS18B20', bus)
    MySensorFabric('3A.000001', 'DS2413', bus)
    MySensorFabric('12.000001', 'DS2406', bus)
    listed = bus.list()
    assert (listed['DS18B20'], listed['DS2413'], listed['DS2406'], listed['DS2438']) == \
        (['28.000001'], ['3A.000001'], ['12.000001'], [])


@pytest.mark.parametrize('configured', [
    '28.A1B2C3D4E5F6.7B',
    '28.A1B2C3D4E5F6',                  # without the CRC
    '28.a1b2c3d4e5f6',                  # lower case
    '28A1B2C3D4E5F67B',                 # without the dots
])
def test_configured_address_matches_the_id_of_owserver(bus, configured):
    """ owserver names the device 28.A1B2C3D4E5F6.7B, the other forms were never found """
    sensor = DS18B20(configured, 'DS18B20', bus, circuit='temp1')
    assert bus._find_sensor('28.A1B2C3D4E5F6.7B') is sensor
    assert bus._find_sensor('28.A1B2C3D4E5F7.7B') is None
    assert address_key(configured) == '28A1B2C3D4E5F6'


def test_ds2404_is_not_supported(bus):
    """ DS2404 has no PIO, its read always failed and it was lost """
    assert MySensorFabric('04.000001', 'DS2404', bus) is None
    assert 'DS2404' not in bus.list()


class FakeServer:
    def __init__(self):
        self.scans = 0

    async def scan_now(self, polling):
        self.scans += 1


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


async def test_scan_interval_0_scans_only_on_request(bus):
    bus.bus_lock = anyio.Lock()
    await bus.set(scan_interval=0)
    server = FakeServer()
    task = asyncio.create_task(bus.scanning(server))
    await settle()
    assert server.scans == 1                            # after the connection
    bus.do_scan()
    await settle()
    assert server.scans == 2
    await bus.set(scan_interval=0, do_scan=True)
    await settle()
    task.cancel()
    assert server.scans == 3


async def test_changed_scan_interval_applies_at_once(bus, monkeypatch):
    """ The wait of the previous interval was finished first, with 0 it was an hour """
    bus.bus_lock = anyio.Lock()
    await bus.set(scan_interval=0)
    server = FakeServer()
    task = asyncio.create_task(bus.scanning(server))
    await settle()
    await bus.set(scan_interval=3600)
    await settle()
    assert server.scans == 1                            # the change does not scan
    bus.scan_interval = 0.01                            # check_interval allows whole seconds only
    bus._wake_scanning()
    await asyncio.sleep(0.05)
    task.cancel()
    assert server.scans >= 2


async def test_do_scan_during_a_scan_scans_again(bus):
    bus.bus_lock = anyio.Lock()
    await bus.set(scan_interval=0)
    server = FakeServer()
    scan_now = server.scan_now

    async def slow_scan(polling):
        if server.scans == 0:
            bus.do_scan()                               # a request during the first scan
        await scan_now(polling)
    server.scan_now = slow_scan
    task = asyncio.create_task(bus.scanning(server))
    await settle()
    task.cancel()
    assert server.scans == 2
