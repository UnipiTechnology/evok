import pytest

from evok.devices import Devices, DI, DO, RO, AI, AO, LED, WATCHDOG, NV_SAVE
from evok.modbus.builder import IOParser
from evok.modbus.digital import DigitalInput, DigitalOutput, ULED
from evok.modbus.special import Watchdog, NvSave
from evok.devices import DATA_POINT, REGISTER
from evok.modbus.analog import AnalogInput, AnalogOutputBrain, DataPoint, OwTemperature

from conftest import make_client, scan


# registers 0..399, a block is read by one request of at most 125 registers
BLOCKS_0_399 = [{'start_reg': start, 'count': 100, 'scan_divider': 1} for start in range(0, 400, 100)]


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
    assert circuits(WATCHDOG) == ['1']                     # one per unit, as NV_SAVE
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
    hw = {'modbus_register_blocks': BLOCKS_0_399,
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


async def test_di_over_16_use_next_register():
    """ The inputs 17-32 read the bits of the inputs 1-16 """
    hw = {'modbus_register_blocks': BLOCKS_0_399,
          'modbus_features': [{'type': 'DI', 'count': 32, 'val_reg': 1, 'counter_reg': 100, 'deboun_reg': 200,
                               'modes': ['Simple', 'DirectSwitch'], 'ds_modes': ['Simple', 'Inverted', 'Toggle'],
                               'direct_reg': 300, 'polar_reg': 310, 'toggle_reg': 320}]}
    client = populate(hw)
    ins = [Devices.by_name(DI, f'1_{i:02d}') for i in range(1, 33)]
    assert [(i.accessor.index, i.accessor.mask) for i in ins[15:17]] == [(1, 1 << 15), (2, 1)]
    dimode = ins[16].dimode
    assert (dimode.accessor_mode.index, dimode.accessor_polarity.index, dimode.accessor_toggle.index) == \
        (301, 311, 321)
    assert (ins[16].accessor_debounce.index, ins[16].accessor_counter.index) == (216, 132)
    client.mb_client.holding.update({1: 0x0001, 2: 0x8002})
    await scan(client, initial=True)
    assert [n + 1 for n, i in enumerate(ins) if i.value] == [1, 18, 32]


@pytest.mark.parametrize('devtype', BIT_IO_FEATURES)
async def test_bit_ios_of_second_feature_use_start_index(devtype):
    """ The relays 17-28 of M403 replaced the relays 1-12, ro 1_01 switched the relay 17 """
    first = dict(BIT_IO_FEATURES[devtype], count=16, start_index=0)
    second = dict(BIT_IO_FEATURES[devtype], count=12, val_reg=2, val_coil=16, start_index=16)
    if devtype == DO:
        second['pwm_reg'] = 116
    client = populate({'modbus_register_blocks': BLOCKS_0_399,
                       'modbus_features': [first, second]})
    assert circuits(devtype) == [f'1_{i:02d}' for i in range(1, 29)]
    io = Devices.by_name(devtype, '1_17')
    assert (io.coil, io.accessor.index, io.accessor.mask) == (16, 2, 1)
    assert Devices.by_name(devtype, '1_01').coil == 0
    assert len(client.eventable_devices) == 28


def test_duplicate_circuit_is_an_error(caplog):
    """ The device with the same circuit replaced the registered one without an error """
    feature = dict(BIT_IO_FEATURES[RO], count=2)
    client = populate({'modbus_register_blocks': [{'start_reg': 0, 'count': 4, 'scan_divider': 1}],
                       'modbus_features': [feature, dict(feature, val_coil=16)]})
    assert [Devices.by_name(RO, c).coil for c in ('1_01', '1_02')] == [0, 1]     # the first feature is kept
    assert len(client.eventable_devices) == 2
    assert 'Duplicate circuit ro 1_01' in caplog.text


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
    return {'modbus_register_blocks': [{'start_reg': 1, 'count': 9, 'scan_divider': 1}],
            'modbus_features': [dict(type='DATA_POINT', count=3, value_reg=1, **feature)]}


def test_data_point_without_valid_mask_reg():
    populate(data_point_hw(datatype='signed16'))
    assert circuits(DATA_POINT) == ['1_1', '1_2', '1_3']
    assert all(type(d) is DataPoint for d in Devices[DATA_POINT].values())
    assert not any(d.writable for d in Devices[DATA_POINT].values())


@pytest.mark.parametrize('datatype, regs', [
    ('float32', [1, 3, 5]),         # were 1, 2, 3 overlapping
    ('uint32', [1, 3, 5]),
    ('uint16', [1, 2, 3]),
])
async def test_data_points_follow_each_other(datatype, regs):
    client = populate(data_point_hw(datatype=datatype))
    assert circuits(DATA_POINT) == [f'1_{reg}' for reg in regs]
    assert [Devices[DATA_POINT][f'1_{reg}'].accessor.index for reg in regs] == regs
    client.mb_client.holding.update({1: 0, 2: 1, 3: 0, 4: 2, 5: 0, 6: 3})
    await scan(client, initial=True)
    if datatype == 'uint32':                                # high word first
        assert [Devices[DATA_POINT][f'1_{reg}'].value for reg in regs] == [1, 2, 3]


def bao_hw(**feature):
    return {'modbus_register_blocks': [{'start_reg': 0, 'count': 8, 'scan_divider': 1}],
            'modbus_features': [dict(type='BAO', val_reg=0, res_val_reg=4, mode_reg=6, **feature)]}


def test_bao_creates_one_output():
    populate(bao_hw(count=1))
    ao = Devices[AO]['1_01']
    assert type(ao) is AnalogOutputBrain
    assert (ao.ao_accessor.index, ao.res_accessor.index, ao.iomode.accessor.index) == (0, 4, 6)
    assert circuits(AO) == ['1_01']


def test_bao_with_more_outputs_is_an_error(caplog):
    populate(bao_hw(count=2))
    assert circuits(AO) == []
    assert 'BAO can have only one output, count is 2' in caplog.text


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


def test_register_is_deprecated(caplog):
    populate({'modbus_register_blocks': [{'start_reg': 0, 'count': 2, 'scan_divider': 1}],
              'modbus_features': [{'type': 'REGISTER', 'count': 2, 'start_reg': 0}]})
    assert circuits(REGISTER) == ['1_0', '1_1']           # still created
    assert caplog.text.count('the feature REGISTER is deprecated') == 1
