from evok.devices import Devices, DI, DO, AI, LED, WATCHDOG, NV_SAVE
from evok.modbus.builder import IOParser
from evok.modbus.digital import DigitalInput, DigitalOutput, ULED
from evok.modbus.special import Watchdog, NvSave
from evok.modbus.analog import AnalogInput

from conftest import make_client, scan


def populate(hw, circuit='1'):
    client = make_client(hw['modbus_register_blocks'])
    IOParser(client, hw['modbus_features'], circuit).populate()
    return client


def circuits(devtype):
    return sorted(Devices[devtype].keys())


def test_l0306_creates_all_devices(l0306):
    populate(l0306)
    assert circuits(DI) == ['1_01', '1_02', '1_03', '1_04']
    assert circuits(DO) == ['1_01', '1_02']
    assert circuits(AI) == ['1_01', '1_02', '1_03', '1_04', '1_05']
    assert circuits(WATCHDOG) == ['1_01']
    assert circuits(NV_SAVE) == ['1']
    assert circuits(LED) == ['1_01', '1_02', '1_03']


def test_l0306_device_classes_and_group(l0306):
    populate(l0306, circuit='7')
    for devtype, cls in ((DI, DigitalInput), (DO, DigitalOutput), (AI, AnalogInput),
                         (WATCHDOG, Watchdog), (NV_SAVE, NvSave), (LED, ULED)):
        for dev in Devices[devtype].values():
            assert isinstance(dev, cls)
            assert dev.major_group == '7'


def test_l0306_eventable_devices(l0306):
    client = populate(l0306)
    # everything with check_new_data; NvSave has none
    assert len(client.eventable_devices) == 4 + 2 + 5 + 1 + 3
    assert not any(isinstance(d, NvSave) for d in client.eventable_devices)


def test_l0306_register_layout(l0306):
    populate(l0306)
    di = Devices.by_name(DI, '1_03')
    assert (di.reg, di.bitmask, di.regcounter, di.regdebounce) == (0, 0b100, 17, 1012)
    assert (di.regmode, di.regpolarity, di.regtoggle) == (1014, 1015, 1016)
    do = Devices.by_name(DO, '1_02')
    assert (do.coil, do.valreg, do.bitmask, do.pwmdutyreg) == (1, 1, 0b10, 22)
    assert (do.pwmcyclereg, do.pwmprescalereg) == (1018, 1017)
    ai = Devices.by_name(AI, '1_05')
    assert (ai.valreg, ai.regmode) == (10, 1023)
    led = Devices.by_name(LED, '1_03')
    assert (led.coil, led.valreg, led.bitmask) == (3002, 3998, 0b100)


def test_unknown_feature_is_skipped(l0306):
    features = [{'type': 'FOO'}] + l0306['modbus_features']
    client = make_client(l0306['modbus_register_blocks'])
    IOParser(client, features, '1').populate()
    assert circuits(DI) == ['1_01', '1_02', '1_03', '1_04']


async def test_all_device_registers_are_covered_by_blocks(l0306):
    """ Every register a device reads during a scan must be in a register block """
    client = populate(l0306)
    changed = await scan(client, initial=True)
    assert len(changed) == len(client.eventable_devices)
