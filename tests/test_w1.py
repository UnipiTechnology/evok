import asyncio
import os
import json
import logging

import pytest

from evok import devents
from evok.devices import Devices, SENSOR
from evok.w1 import DS18B20, DS2408, DS2438, OwBusDriver, MySensorFabric, address_key
from evok.w1 import bus as w1_bus, sysfs as w1_sysfs
from evok.w1.bus import leaf_error


@pytest.fixture
def events(monkeypatch):
    sent = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: sent.append(device))
    return sent


@pytest.fixture
def bus():
    return OwBusDriver('OW', interval=10)


class FakeSens:
    """ A device of the bus returning the given fields """
    def __init__(self, **fields):
        self.fields = fields

    async def get(self, field):
        return self.fields[field]

    async def get_sensed_all(self):
        return self.fields['sensed_all']


async def read(bus, sensor):
    """ One read of the sensor by poll() """
    bus.bus_lock = asyncio.Lock()
    await bus.read_sensor(sensor, asyncio.get_running_loop().time())


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
    sensor.sens = FakeSens(**{'temperature': 21.0, 'VDD': 5.0, 'VAD': 2.0, 'vis': 0.1})
    await read(bus, sensor)
    assert events == [sensor]
    assert sensor.get_value() == (5.0, 2.0, 21.0, None)
    await read(bus, sensor)
    assert events == [sensor]                           # no change, no event
    sensor.sens.fields['temperature'] = 22.0
    await read(bus, sensor)
    assert events == [sensor, sensor]
    assert sensor.full()['temp'] == 22.0
    # HIH4000: (VAD / VDD - 0.16) / (0.0062 * (1.0546 - 0.00216 * T)), computed as by owfs
    assert sensor.full()['humidity'] == 38.44


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
    monkeypatch.setattr(w1_bus, 'RECONNECT_DELAY', 0)
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    sensor.sens = FakeSens(temperature=21.0)
    runs = []

    async def run():
        runs.append(None)
        if len(runs) < 3:
            raise FileNotFoundError("1-Wire master 'w1_bus_master1' not found")
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
    assert caplog.text.count('trying again') == 1          # the same error is logged once


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
    bus.bus_lock = asyncio.Lock()
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
    '28-f6e5d4c3b2a1',                  # the name in sysfs, the serial number reversed
])
def test_configured_address_matches_the_id_of_owserver(bus, configured):
    """ owserver named the device 28.A1B2C3D4E5F6.7B, the other forms were never found """
    sensor = DS18B20(configured, 'DS18B20', bus, circuit='temp1')
    assert bus._find_sensor('28.A1B2C3D4E5F6.7B') is sensor
    assert bus._find_sensor('28.A1B2C3D4E5F7.7B') is None
    assert address_key(configured) == '28A1B2C3D4E5F6'


def test_ds2404_is_not_supported(bus):
    """ DS2404 has no PIO, its read always failed and it was lost """
    assert MySensorFabric('04.000001', 'DS2404', bus) is None
    assert 'DS2404' not in bus.list()


async def settle():
    for _ in range(10):
        await asyncio.sleep(0)


async def settle_reads():
    """ The reads of sysfs run in a thread """
    for _ in range(10):
        await asyncio.sleep(0.01)


# ---- the 1-Wire subsystem of the kernel ----

@pytest.mark.parametrize('name, address', [
    ('28-00000925204e', '28.4E2025090000.FF'),          # the ROM 28 4e 20 25 09 00 00 ff of a DS18B20
    ('10-000802b54c1a', '10.1A4CB5020800.8E'),
])
def test_owfs_address_of_a_sysfs_name(name, address):
    """ The circuits of the found sensors stayed the same as with owserver """
    assert w1_sysfs.owfs_address(name) == address
    assert address_key(name) == address_key(address)
    assert w1_sysfs.crc8(bytes.fromhex(address_key(address) + address[-2:])) == 0


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    """ /sys/bus/w1/devices with the master w1_bus_master1 """
    monkeypatch.setattr(w1_sysfs, 'W1_DEVICES', str(tmp_path))
    master = tmp_path / 'w1_bus_master1'
    master.mkdir()

    class Tree:
        path = tmp_path

        @staticmethod
        def slaves(*names):
            (master / 'w1_master_slaves').write_text(''.join(f"{name}\n" for name in names) or 'not found.\n')

        @staticmethod
        def device(name, **attributes):
            (tmp_path / name).mkdir(exist_ok=True)
            for attribute, value in attributes.items():
                data = value if isinstance(value, bytes) else f"{value}\n".encode()
                (tmp_path / name / attribute).write_bytes(data)
    Tree.slaves()
    return Tree


def test_masters(sysfs):
    for n in (10, 2):
        (sysfs.path / f'w1_bus_master{n}').mkdir()
    assert w1_sysfs.masters() == ['w1_bus_master1', 'w1_bus_master2', 'w1_bus_master10']
    assert w1_sysfs.W1Master().name == 'w1_bus_master1'
    with pytest.raises(FileNotFoundError, match="1-Wire master 'w1_bus_master3' not found"):
        w1_sysfs.W1Master('w1_bus_master3')


def test_no_master(tmp_path, monkeypatch):
    monkeypatch.setattr(w1_sysfs, 'W1_DEVICES', str(tmp_path / 'missing'))
    with pytest.raises(FileNotFoundError, match='no 1-Wire master'):
        w1_sysfs.W1Master()


async def test_slaves(sysfs):
    master = w1_sysfs.W1Master()
    assert await master.slaves() == []                  # 'not found.'
    sysfs.slaves('28-00000925204e', '29-0000001b2c3d')
    assert await master.slaves() == ['28-00000925204e', '29-0000001b2c3d']


@pytest.mark.parametrize('name, attributes, field, value', [
    ('28-00000925204e', {'temperature': 25062}, 'temperature', 25.062),
    ('10-000802b54c1a', {'temperature': -1500}, 'temperature', -1.5),
    ('26-000000a1b2c3', {'temperature': 5632}, 'temperature', 22.0),        # 1/256 C
    ('26-000000a1b2c3', {'vdd': 500}, 'VDD', 5.0),                          # 10 mV
    ('26-000000a1b2c3', {'vad': 213}, 'VAD', 2.13),
    ('26-000000a1b2c3', {'iad': -41}, 'vis', -41 * 0.0002441),              # 0.2441 mV
])
async def test_device_values(sysfs, name, attributes, field, value):
    sysfs.device(name, **attributes)
    assert await w1_sysfs.W1Master().device(name).get(field) == pytest.approx(value)


@pytest.mark.parametrize('name, state, sensed', [
    ('29-0000001b2c3d', b'\x05', [1, 0, 1, 0, 0, 0, 0, 0]),     # DS2408, the PIO logic state
    ('3a-0000001b2c3d', b'\x84', [0, 1]),                       # DS2413, PIOB in bit 2
    ('3a-0000001b2c3d', b'\x0f', [1, 1]),
    ('12-0000001b2c3d', b'\x32', [0, 1]),                       # DS2406, the channel flip-flops
])
async def test_device_sensed(sysfs, name, state, sensed):
    sysfs.device(name, state=state)
    assert await w1_sysfs.W1Master().device(name).get_sensed_all() == sensed


async def test_failed_read_raises(sysfs):
    """ A device which does not answer or a CRC error, the driver returns EIO; here a missing attribute """
    sysfs.device('28-00000925204e')
    with pytest.raises(OSError):
        await w1_sysfs.W1Master().device('28-00000925204e').get('temperature')


async def scan_once(bus, sysfs):
    """ One scan of the bus by scanning() """
    bus.bus_lock = asyncio.Lock()
    await bus.set(scan_interval=0)
    task = asyncio.create_task(bus.scanning(w1_sysfs.W1Master()))
    await settle_reads()
    return task


async def test_scan_creates_the_found_sensors(bus, sysfs, caplog):
    caplog.set_level(logging.INFO, logger='evok')
    sysfs.slaves('28-00000925204e', '29-0000001b2c3d', '01-000012345678')
    sysfs.device('28-00000925204e', temperature=25062)
    task = await scan_once(bus, sysfs)
    task.cancel()
    temp, gpio = bus.mysensors
    assert (temp.address, temp.circuit, temp.type) == ('28.4E2025090000.FF', '284E2025090000FF', 'DS18B20')
    assert (gpio.address, gpio.circuit, gpio.type) == ('29.3D2C1B000000.F1', '29.3D2C1B000000.F1', 'DS2408')
    assert await temp.sens.get('temperature') == 25.062
    assert caplog.text.count('Unsupported 1wire device None (01.785634120000') == 1


async def test_scan_assigns_a_configured_sensor_and_reports_a_missing_one(bus, sysfs, events, caplog):
    caplog.set_level(logging.INFO, logger='evok')
    configured = DS18B20('28-00000925204e', 'DS18B20', bus, circuit='boiler')
    missing = DS18B20('28.000000000001', 'DS18B20', bus, circuit='missing')
    sysfs.slaves('28-00000925204e')
    task = await scan_once(bus, sysfs)
    events.clear()
    bus.do_scan()                                       # the next scan does not report it again
    await settle_reads()
    task.cancel()
    assert (configured.sens.path, configured.lost) == (str(sysfs.path / '28-00000925204e'), False)
    assert (missing.sens, missing.lost) == (None, True)
    assert bus.mysensors == [configured, missing]       # no sensor of the found one
    assert caplog.text.count('Sensor missing (28.000000000001) not found on the bus') == 1
    assert events == []


async def test_disappeared_sensor_is_lost_and_found_again(bus, sysfs, events, caplog):
    caplog.set_level(logging.INFO, logger='evok')
    sysfs.slaves('28-00000925204e')
    task = await scan_once(bus, sysfs)
    sensor, = bus.mysensors
    sysfs.slaves()
    bus.do_scan()
    await settle_reads()
    assert (sensor.sens, sensor.lost) == (None, True)
    assert 'Sensor 284E2025090000FF (28.4E2025090000.FF) disappeared' in caplog.text
    sysfs.slaves('28-00000925204e')
    bus.do_scan()
    await settle_reads()
    task.cancel()
    assert sensor.sens is not None and sensor.time == 0      # read at once, the read reports the recovery
    assert 'Sensor 284E2025090000FF found' in caplog.text


async def test_failed_scan_ends_the_bus(bus, sysfs):
    """ The master disappeared, e.g. its driver was removed; run_forever() uses it again later """
    (sysfs.path / 'w1_bus_master1' / 'w1_master_slaves').unlink()
    bus.bus_lock = asyncio.Lock()
    with pytest.raises(FileNotFoundError):
        await bus.scanning(w1_sysfs.W1Master())


async def test_scan_interval_0_scans_only_on_request(bus, sysfs, monkeypatch):
    scans = []
    slaves = w1_sysfs.W1Master.slaves

    async def counted(self):
        scans.append(None)
        return await slaves(self)
    monkeypatch.setattr(w1_sysfs.W1Master, 'slaves', counted)
    task = await scan_once(bus, sysfs)
    assert len(scans) == 1                              # after the start
    bus.do_scan()
    await settle_reads()
    assert len(scans) == 2
    await bus.set(scan_interval=0, do_scan=True)
    await settle_reads()
    assert len(scans) == 3
    await bus.set(scan_interval=3600)
    await settle_reads()
    assert len(scans) == 3                              # the change does not scan
    bus.scan_interval = 0.01                            # check_interval allows whole seconds only
    bus._wake_scanning()
    await asyncio.sleep(0.05)
    task.cancel()
    assert len(scans) >= 4                              # the changed interval applies at once


async def test_run_uses_the_master(bus, sysfs, caplog):
    caplog.set_level(logging.INFO, logger='evok')
    sysfs.slaves('28-00000925204e')
    sysfs.device('28-00000925204e', temperature=21500)
    task = asyncio.create_task(bus.run())
    for _ in range(100):
        if bus.mysensors and bus.mysensors[0].value is not None:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    assert bus.mysensors[0].value == 21.5
    assert bus.full()['master'] == 'w1_bus_master1'
    assert '1-Wire bus OW uses the master w1_bus_master1' in caplog.text


def refused():
    """ An OSError in nested task groups """
    error = OSError('All connection attempts failed')
    error.__cause__ = ConnectionRefusedError(111, "Connect call failed ('127.0.0.1', 4304)")
    return ExceptionGroup('unhandled errors in a TaskGroup', [ExceptionGroup('unhandled errors in a TaskGroup',
                                                                             [error])])


def test_leaf_error():
    assert type(leaf_error(refused())) is ConnectionRefusedError
    error = ValueError('x')
    assert leaf_error(error) is error


async def run_bus(bus, monkeypatch, run, runs):
    """ Run the bus until run() was called runs times """
    monkeypatch.setattr(w1_bus, 'RECONNECT_DELAY', 0)
    calls = []

    async def counted():
        calls.append(None)
        if len(calls) > runs:
            await asyncio.Event().wait()
        await run(len(calls))
    monkeypatch.setattr(bus, 'run', counted)
    bus.start_scanning()
    for _ in range(100):
        if len(calls) > runs:
            break
        await asyncio.sleep(0)
    bus._run_task.cancel()
    assert len(calls) > runs


def missing_master():
    return ExceptionGroup('unhandled errors in a TaskGroup',
                          [FileNotFoundError("1-Wire master 'w1_bus_master1' not found in /sys/bus/w1/devices")])


async def test_missing_master_is_logged_once(bus, monkeypatch, caplog):
    async def run(n):
        raise missing_master()
    await run_bus(bus, monkeypatch, run, 3)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert ("1-Wire bus OW: cannot use the 1-Wire master, is its driver loaded (e.g. ds2482)? "
            "FileNotFoundError: 1-Wire master 'w1_bus_master1' not found") in errors[0]
    assert 'ExceptionGroup' not in caplog.text


async def test_master_after_a_failure_is_logged(bus, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='evok')

    async def run(n):
        if n == 3:
            bus._log_connected()                # the master is found, then it fails again
        raise missing_master()
    await run_bus(bus, monkeypatch, run, 4)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert ['uses the master' in m for m in messages] == [False, True, False]   # the next failure is logged again


async def test_failure_after_every_start_is_logged_once(bus, monkeypatch, caplog):
    """ A failure after the start reset the logged error, it was logged after every start """
    caplog.set_level(logging.INFO, logger='evok')

    async def run(n):
        bus._log_connected()
        raise ValueError('a bug')
    await run_bus(bus, monkeypatch, run, 3)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert len(messages) == 2
    assert 'uses the master' in messages[0] and 'ValueError: a bug' in messages[1]


async def test_configured_sensor_is_not_lost_before_it_is_located(bus, monkeypatch):
    """ #231: poll() read the sensor without its device at the start and reported it lost """
    states = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: states.append((device.circuit, device.lost)))
    bus.bus_lock = asyncio.Lock()
    sensor = DS18B20('28.A1B2C3D4E5F6', 'DS18B20', bus, circuit='temp1')
    task = asyncio.create_task(bus.poll())
    await settle()
    assert (sensor.lost, states) == (False, [])          # not read without sens
    sensor.sens = FakeSens(temperature=21.5)             # found by the scan
    bus.wake()
    await settle()
    task.cancel()
    assert (sensor.value, sensor.lost, states) == (21.5, False, [('temp1', False)])


async def test_found_sensor_with_the_circuit_of_a_sensor_is_skipped(bus, caplog):
    """ #230: a configured sensor named by the circuit of a found one, the found one replaced it """
    other = OwBusDriver('OW2', master='w1_bus_master2')
    configured = DS18B20('28.000000000001', 'DS18B20', other, circuit='28A1B2C3D4E5F67B')
    assert bus._create_found('28.A1B2C3D4E5F6.7B', 'DS18B20') is None
    assert bus._create_found('28.A1B2C3D4E5F6.7B', 'DS18B20') is None     # the next scan
    assert Devices[SENSOR]['28A1B2C3D4E5F67B'] is configured
    assert bus.mysensors == []
    assert caplog.text.count("has the same name as the sensor 28.000000000001 of bus 'OW2', "
                             "the found sensor is skipped") == 1
    assert bus._create_found('28.A1B2C3D4E5F7.7B', 'DS18B20').circuit == '28A1B2C3D4E5F77B'


async def test_failed_scan_ends_run(bus, sysfs):
    """ The task group cancels poll() after a failure of the scan, run_forever() starts the bus again """
    (sysfs.path / 'w1_bus_master1' / 'w1_master_slaves').unlink()
    with pytest.raises(ExceptionGroup) as error:
        await asyncio.wait_for(bus.run(), 1)
    assert type(leaf_error(error.value)) is FileNotFoundError


# ---- the forced search and the bulk conversion ----

@pytest.mark.parametrize('count, written', [('-1', '-1\n'), ('0', '1\n'), ('5', '5\n')])
async def test_search_keeps_the_count_of_the_searches(sysfs, count, written):
    """ The count is written back, -1 keeps the continual search of the kernel, it only wakes up """
    search = sysfs.path / 'w1_bus_master1' / 'w1_master_search'
    search.write_text(f"{count}\n")
    master = w1_sysfs.W1Master()
    assert master.can_search()
    await master.search()
    assert search.read_text() == written


async def test_do_scan_forces_a_search(bus, sysfs, monkeypatch):
    monkeypatch.setattr(w1_bus, 'SEARCH_WAIT', 0)
    search = sysfs.path / 'w1_bus_master1' / 'w1_master_search'
    search.write_text('-1\n')
    writes = []
    write_text = w1_sysfs._write_text
    monkeypatch.setattr(w1_sysfs, '_write_text', lambda path, text: (writes.append(text), write_text(path, text)))
    task = await scan_once(bus, sysfs)
    assert writes == []                                 # not the scan after the start
    sysfs.slaves('28-00000925204e')                     # found by the search
    bus.do_scan()
    await settle_reads()
    task.cancel()
    assert writes == ['-1\n']
    assert [s.address for s in bus.mysensors] == ['28.4E2025090000.FF']


@pytest.mark.skipif(os.geteuid() == 0, reason='root has the write access')
async def test_do_scan_without_the_write_access(bus, sysfs, caplog):
    """ The search of the kernel is taken, the missing access is logged once """
    caplog.set_level(logging.INFO, logger='evok')
    search = sysfs.path / 'w1_bus_master1' / 'w1_master_search'
    search.write_text('-1\n')
    search.chmod(0o444)
    task = await scan_once(bus, sysfs)
    sysfs.slaves('28-00000925204e')
    for _ in range(2):
        bus.do_scan()
        await settle_reads()
    task.cancel()
    assert [s.address for s in bus.mysensors] == ['28.4E2025090000.FF']
    assert caplog.text.count('a forced search needs the write access to w1_bus_master1/w1_master_search') == 1


def thermometers(bus, sysfs, *names, interval=10):
    """ Found thermometers due now """
    for n, name in enumerate(names):
        sysfs.device(name, temperature=20000 + n * 1000)
    master = w1_sysfs.W1Master()
    sensors = [DS18B20(w1_sysfs.owfs_address(name), 'DS18B20', bus, interval=interval) for name in names]
    for sensor, name in zip(sensors, names):
        sensor.sens = master.device(name)
    bus._master = master
    bus.bus_lock = asyncio.Lock()
    return sensors


async def poll_once(bus):
    task = asyncio.create_task(bus.poll())
    await settle_reads()
    task.cancel()


async def test_thermometers_are_converted_together(bus, sysfs, events, monkeypatch):
    """ One conversion of all thermometers instead of 750 ms for each one """
    bulk = sysfs.path / 'w1_bus_master1' / 'therm_bulk_read'
    bulk.write_text('0\n')
    writes = []
    monkeypatch.setattr(w1_sysfs, '_write_text', lambda path, text: writes.append((os.path.basename(path), text)))
    first, second = thermometers(bus, sysfs, '28-00000925204e', '28-000009251111')
    second.time = asyncio.get_running_loop().time() + 4      # due in the half of its interval
    await poll_once(bus)
    assert writes == [('therm_bulk_read', 'trigger\n')]
    assert (first.value, second.value) == (20.0, 21.0)


async def test_one_thermometer_is_not_converted_together(bus, sysfs, monkeypatch):
    (sysfs.path / 'w1_bus_master1' / 'therm_bulk_read').write_text('0\n')
    writes = []
    monkeypatch.setattr(w1_sysfs, '_write_text', lambda path, text: writes.append(text))
    first, second = thermometers(bus, sysfs, '28-00000925204e', '28-000009251111')
    second.time = asyncio.get_running_loop().time() + 6      # due later than in the half of its interval
    await poll_once(bus)
    assert writes == []
    assert (first.value, second.value) == (20.0, None)


@pytest.mark.skipif(os.geteuid() == 0, reason='root has the write access')
async def test_thermometers_without_the_bulk_access_convert_one_by_one(bus, sysfs, caplog):
    caplog.set_level(logging.INFO, logger='evok')
    bulk = sysfs.path / 'w1_bus_master1' / 'therm_bulk_read'
    bulk.write_text('0\n')
    bulk.chmod(0o444)
    first, second = thermometers(bus, sysfs, '28-00000925204e', '28-000009251111')
    await poll_once(bus)
    assert (first.value, second.value) == (20.0, 21.0)
    assert caplog.text.count('needs the write access to w1_bus_master1/therm_bulk_read') == 1


async def test_failed_bulk_conversion_converts_one_by_one(bus, sysfs, monkeypatch, caplog):
    (sysfs.path / 'w1_bus_master1' / 'therm_bulk_read').write_text('0\n')

    def failed(path, text):
        raise OSError(5, 'Input/output error')
    monkeypatch.setattr(w1_sysfs, '_write_text', failed)
    first, second = thermometers(bus, sysfs, '28-00000925204e', '28-000009251111')
    await poll_once(bus)
    assert (first.value, second.value) == (20.0, 21.0)
    assert caplog.text.count('conversion of all thermometers failed') == 1



async def test_comm_of_a_sensor(bus, events):
    """ #201: the communication as of a device of a Modbus unit """
    sensor = DS18B20('28.000001', 'DS18B20', bus)
    assert (sensor.full()['comm'], sensor.full()['last_comm']) == ('ok', None)       # not read yet
    sensor.sens = FakeSens(temperature=21.5)
    await read(bus, sensor)
    assert sensor.full()['comm'] == 'ok' and 0 <= sensor.full()['last_comm'] < 1
    sensor.sens = None
    await read(bus, sensor)
    assert sensor.full()['comm'] == 'timeout'
