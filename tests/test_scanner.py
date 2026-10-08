import asyncio

import pytest
from tmodbus import AsyncSmartTransport, AsyncTcpTransport
from tmodbus.exceptions import RequestRetryFailedError

from evok.devices import Devices, DI
from evok.modbus.scanner import ModbusScanner

from conftest import FakeModbus


def make_scanner(l0306, scan_freq=50, scan_enabled=True):
    scanner = ModbusScanner(AsyncSmartTransport(AsyncTcpTransport('127.0.0.1', 502)), '1', scan_freq,
                            scan_enabled, l0306, unit_id=1)
    mb = FakeModbus()
    scanner.cache.modbus_client = scanner.client.mb_client = mb
    return scanner, mb


@pytest.mark.parametrize('scan_freq', [0, -1, '50', True, None])
def test_invalid_scan_frequency(l0306, scan_freq):
    # 0 scanned the bus without a pause
    with pytest.raises(ValueError, match='scan_frequency'):
        make_scanner(l0306, scan_freq)


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
