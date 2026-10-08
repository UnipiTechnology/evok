import pytest

from evok.devices import Devices, DI, DO, RO, AI, LED, WATCHDOG, NV_SAVE
from evok.modbus.builder import IOParser
from evok.modbus.digital import DigitalInput, DigitalOutput, ULED
from evok.modbus.special import Watchdog, NvSave
from evok.devices import DATA_POINT
from evok.modbus.analog import AnalogInput, DataPoint, OwTemperature

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
    assert (di.accessor.index, di.accessor.mask, di.accessor_counter.index, di.accessor_debounce.index) == (0, 0b100, 17, 1012)
    assert (di.dimode.accessor_mode.index, di.dimode.accessor_polarity.index,
            di.dimode.accessor_toggle.index) == (1014, 1015, 1016)
    do = Devices.by_name(DO, '1_02')
    assert (do.coil, do.accessor.index, do.accessor.mask, do.accessor_pwm_duty.index) == (1, 1, 0b10, 22)
    assert (do.pwm.accessor_cycle.index, do.pwm.accessor_prescale.index) == (1018, 1017)
    assert do.pwm is Devices.by_name(DO, '1_01').pwm
    ai = Devices.by_name(AI, '1_05')
    assert (ai.accessor.index, ai.iomode.accessor.index) == (10, 1023)
    led = Devices.by_name(LED, '1_03')
    assert (led.coil, led.accessor.index, led.accessor.mask) == (3002, 3998, 0b100)


BIT_IO_FEATURES = {
    RO: {'type': 'RO', 'val_reg': 1, 'val_coil': 0},
    LED: {'type': 'LED', 'val_reg': 1, 'val_coil': 0},
    DO: {'type': 'DO', 'val_reg': 1, 'val_coil': 0, 'modes': ['Simple', 'PWM'],
         'pwm_reg': 100, 'pwm_ps_reg': 140, 'pwm_c_reg': 141},
}


@pytest.mark.parametrize('devtype', BIT_IO_FEATURES)
async def test_bit_ios_over_16_use_next_register(devtype):
    hw = {'modbus_register_blocks': [{'start_reg': 0, 'count': 400, 'frequency': 1}],
          'modbus_features': [dict(BIT_IO_FEATURES[devtype], count=32)]}
    client = populate(hw)
    ios = [Devices.by_name(devtype, f'1_{i:02d}') for i in range(1, 33)]
    assert [(io.accessor.index, io.accessor.mask) for io in ios[14:18]] == \
        [(1, 1 << 14), (1, 1 << 15), (2, 1), (2, 1 << 1)]
    assert (ios[31].accessor.index, ios[31].accessor.mask) == (2, 1 << 15)
    assert [io.coil for io in ios[14:18]] == [14, 15, 16, 17]
    client.mb_client.holding.update({1: 0x0001, 2: 0x8002})
    await scan(client, initial=True)
    assert [i + 1 for i, io in enumerate(ios) if io.value] == [1, 18, 32]


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


def data_point_hw(**feature):
    return {'modbus_register_blocks': [{'start_reg': 1, 'count': 9, 'frequency': 1}],
            'modbus_features': [dict(type='DATA_POINT', count=3, value_reg=1, **feature)]}


def test_data_point_without_valid_mask_reg():
    populate(data_point_hw(datatype='signed16'))
    assert circuits(DATA_POINT) == ['1_1', '1_2', '1_3']
    assert all(type(d) is DataPoint for d in Devices[DATA_POINT].values())
    assert not any(d.writable for d in Devices[DATA_POINT].values())


def test_invalid_feature_is_skipped(caplog):
    hw = data_point_hw(datatype='bogus')
    hw['modbus_features'].append(dict(type='DATA_POINT', count=1, value_reg=5))
    populate(hw)
    assert circuits(DATA_POINT) == ['1_5']                 # the other features are created
    assert 'Invalid feature DATA_POINT' in caplog.text


def test_data_point_writable():
    populate(data_point_hw(writable=True))
    assert all(d.writable for d in Devices[DATA_POINT].values())


def test_data_point_with_valid_mask_reg_is_ow_temperature():
    """ xG18: 8 thermometers with the validity bits in one register """
    populate(data_point_hw(valid_mask_reg=9, factor=0.01, unit='C', name='temperature'))
    devs = [Devices[DATA_POINT][c] for c in circuits(DATA_POINT)]
    assert all(type(d) is OwTemperature for d in devs)
    assert [(d.accessor.index, d.accessor_valid.index, d.accessor_valid.mask) for d in devs] == \
        [(1, 9, 0b001), (2, 9, 0b010), (3, 9, 0b100)]
    assert devs[0].accessor.ratio == 0.01 and devs[0].unit == 'C' and devs[0].major_group == '1'
