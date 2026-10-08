import asyncio

import pytest
from tmodbus import AsyncRtuTransport, AsyncSmartTransport, AsyncTcpTransport
from tmodbus.exceptions import RequestRetryFailedError

from evok.devices import Devices, DI
from evok.modbus.scanner import ModbusScanner

from conftest import FakeModbus


def make_scanner(l0306, scan_freq=50, scan_enabled=True, unit_id=1):
    scanner = ModbusScanner(AsyncSmartTransport(AsyncTcpTransport('127.0.0.1', 502)), '1', scan_freq,
                            scan_enabled, l0306, unit_id=unit_id)
    mb = FakeModbus()
    scanner.cache.modbus_client = scanner.client.mb_client = mb
    return scanner, mb


@pytest.mark.parametrize('scan_freq', [0, -1, '50', True, None])
def test_invalid_scan_frequency(l0306, scan_freq):
    # 0 scanned the bus without a pause
    with pytest.raises(ValueError, match='scan_frequency'):
        make_scanner(l0306, scan_freq)


@pytest.mark.parametrize('scan_enabled', ['false', 0, None])
def test_invalid_scan_enabled(l0306, scan_enabled):
    # the string 'false' enabled the scan
    with pytest.raises(ValueError, match='scan_enabled'):
        make_scanner(l0306, scan_enabled=scan_enabled)


@pytest.mark.parametrize('unit_id', [-1, 256, '1', True, None])
def test_invalid_tcp_unit_id(l0306, unit_id):
    # True was the unit 1, a string failed on the first request
    with pytest.raises(ValueError, match='slave-id'):
        make_scanner(l0306, unit_id=unit_id)


@pytest.mark.parametrize('unit_id, valid', [(0, False), (1, True), (247, True), (248, False)])
def test_rtu_unit_id(l0306, unit_id, valid):
    """ 0 is the broadcast of RTU, the unit does not respond """
    transport = AsyncSmartTransport(AsyncRtuTransport('/dev/null'))
    if valid:
        assert ModbusScanner(transport, '1', 50, True, l0306, unit_id=unit_id).modbus_address == unit_id
    else:
        with pytest.raises(ValueError, match=r'slave-id must be an integer 1\.\.247'):
            ModbusScanner(transport, '1', 50, True, l0306, unit_id=unit_id)


def test_tcp_gateway_unit_id(l0306):
    for unit_id in (0, 255):
        assert make_scanner(l0306, unit_id=unit_id)[0].modbus_address == unit_id


def test_full_reports_scan_enabled(l0306):
    assert make_scanner(l0306)[0].full()['scan_enabled'] is True
    assert make_scanner(l0306, scan_enabled=False)[0].full()['scan_enabled'] is False


async def test_devices_are_created_without_scan_enabled(l0306):
    """ Without scan_enabled the unit had no devices, they are created by the first scan """
    scanner, mb = make_scanner(l0306, scan_enabled=False)
    scanner.start_scanning()
    await asyncio.wait_for(scanner.scan_task, 1)                # no periodic scan
    assert sorted(Devices[DI]) == ['1_01', '1_02', '1_03', '1_04']
    assert scanner.full()['last_comm'] is not None


async def test_scan_error_is_reported(l0306):
    scanner, mb = make_scanner(l0306)
    assert (scanner.full()['last_comm'], scanner.full()['scan_error']) == (None, None)

    async def fail(*args, **kwargs):
        raise RequestRetryFailedError('no response')
    read = mb.read_holding_registers
    mb.read_holding_registers = fail
    assert not await scanner.cache.do_scan(initial=True)
    assert scanner.full()['scan_error'] == 'RequestRetryFailedError: no response'
    mb.read_holding_registers = read
    assert await scanner.cache.do_scan(initial=True)
    assert scanner.full()['scan_error'] is None


async def test_unexpected_error_of_scan_task_is_logged(l0306, caplog):
    scanner, mb = make_scanner(l0306)

    def broken():
        raise RuntimeError('bug')
    scanner.parser.populate = broken
    scanner.start_scanning()
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(scanner.scan_task, 1)
    await asyncio.sleep(0)                                      # the done callback
    assert "Scan of device '1' stopped" in caplog.text
    assert 'RuntimeError: bug' in caplog.text


async def test_started_again_scan_does_not_create_devices_again(l0306):
    """ Without scan_enabled the task is done after the first scan, a new start registered the devices twice """
    scanner, mb = make_scanner(l0306, scan_enabled=False)
    scanner.start_scanning()
    await asyncio.wait_for(scanner.scan_task, 1)

    def populate_again():
        raise AssertionError('the devices are created again')
    scanner.parser.populate = populate_again
    scanner.start_scanning()
    await asyncio.wait_for(scanner.scan_task, 1)
    assert sorted(Devices[DI]) == ['1_01', '1_02', '1_03', '1_04']


async def test_unexpected_error_of_scan_is_reported(l0306):
    """ Only the communication errors were reported by full(), the scan_error of a failing scan was null """
    scanner, mb = make_scanner(l0306)
    assert await scanner.cache.do_scan(initial=True)

    async def broken():
        raise RuntimeError('bug')
    scanner.client.do_scan = broken
    assert not await scanner._scan_unit()
    assert scanner.full()['scan_error'] == 'RuntimeError: bug'


async def test_repeated_unexpected_error_of_scan_is_logged_once(l0306, caplog):
    """ The traceback of the same error was logged on every scan """
    scanner, mb = make_scanner(l0306)
    assert await scanner.cache.do_scan(initial=True)
    do_scan = scanner.client.do_scan

    async def broken():
        raise RuntimeError('bug')
    scanner.client.do_scan = broken
    for _ in range(3):
        assert not await scanner._scan_unit()
    assert caplog.text.count('RuntimeError: bug') == 1

    scanner.client.do_scan = do_scan                            # a successful scan logs the error again
    assert await scanner._scan_unit()
    scanner.client.do_scan = broken
    assert not await scanner._scan_unit()
    assert caplog.text.count('RuntimeError: bug') == 2


async def test_scan_interval_is_period_of_scans(l0306):
    """ The pause after a scan was the interval, a scan of 30 ms at 20 Hz was repeated every 80 ms """
    scanner, mb = make_scanner(l0306, scan_freq=20)
    scanner.populated = True
    scans = []

    async def slow_scan():
        scans.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.03)
        return True
    scanner.client.do_scan = slow_scan
    scanner.start_scanning()
    await asyncio.sleep(1)
    await scanner.stop_scanning()
    assert len(scans) >= 17                                     # 20 per second, 12 with the pause after a scan


async def test_long_scan_is_not_caught_up(l0306):
    """ A scan longer than the interval is followed by the next one, without a burst of the missed ones """
    scanner, mb = make_scanner(l0306, scan_freq=20)
    scanner.populated = True
    scans = []

    async def scan():
        scans.append(asyncio.get_running_loop().time())
        await asyncio.sleep(0.3 if len(scans) == 1 else 0)
        return True
    scanner.client.do_scan = scan
    scanner.start_scanning()
    await asyncio.sleep(0.5)
    await scanner.stop_scanning()
    assert scans[2] - scans[1] > 0.04                           # not the 5 missed scans at once


async def test_stop_scanning_waits_for_scan(l0306):
    """ stop_scanning() was never called, the units were scanned during the shutdown """
    scanner, mb = make_scanner(l0306)
    scanner.populated = True
    scanning = asyncio.Event()

    async def endless_scan():
        scanning.set()
        await asyncio.sleep(10)
    scanner.client.do_scan = endless_scan
    scanner.start_scanning()
    await asyncio.wait_for(scanning.wait(), 1)
    task = scanner.scan_task
    await scanner.stop_scanning()
    assert task.cancelled() and scanner.scan_task is None
    await scanner.stop_scanning()                               # stopped twice


async def test_stop_scanning_after_error_of_scan_task(l0306, caplog):
    scanner, mb = make_scanner(l0306)

    def broken():
        raise RuntimeError('bug')
    scanner.parser.populate = broken
    scanner.start_scanning()
    await asyncio.wait([scanner.scan_task])
    await scanner.stop_scanning()                               # the error is not raised again
    assert caplog.text.count('RuntimeError: bug') == 1
