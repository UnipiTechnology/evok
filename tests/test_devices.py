import asyncio
import math

import pytest

from evok.devices import Devices, DI, DO, AI, LED, WATCHDOG
from evok.modbus.analog import AnalogInput, AnalogOutput, AnalogOutputBrain, DataPoint, OwTemperature, Register
from evok.modbus.builder import IOParser
from evok.modbus.client import to_registers, FLOAT32_LE, FLOAT32_BE
from evok.modbus.special import NvSave

from conftest import make_client, scan


@pytest.fixture
def unit(l0306):
    """ Populated L0306 unit '1'; call it with the initial holding registers """
    async def factory(holding=None):
        client = make_client(l0306['modbus_register_blocks'], holding)
        IOParser(client, l0306['modbus_features'], '1').populate()
        await scan(client, initial=True)
        return client
    return factory


def dev(devtype, circuit):
    return Devices.by_name(devtype, circuit)


# --- DigitalInput -----------------------------------------------------------

async def test_di_value_counter_debounce(unit):
    await unit({0: 0b0101, 13: 0x0002, 14: 0x0001, 1010: 50, 1011: 20})
    assert dev(DI, '1_01').value == 1
    assert dev(DI, '1_02').value == 0
    assert dev(DI, '1_03').value == 1
    assert dev(DI, '1_01').counter == 0x10002       # low word first
    assert (dev(DI, '1_01').debounce, dev(DI, '1_02').debounce) == (50, 20)


async def test_di_change_is_reported(unit):
    client = await unit()
    client.mb_client.holding[0] = 0b10
    assert await scan(client) == [dev(DI, '1_02')]


async def test_di_direct_switch_mode_from_registers(unit):
    await unit({1014: 0b0011, 1015: 0b0001, 1016: 0b0010})
    assert (dev(DI, '1_01').mode, dev(DI, '1_01').ds_mode) == ('DirectSwitch', 'Inverted')
    assert (dev(DI, '1_02').mode, dev(DI, '1_02').ds_mode) == ('DirectSwitch', 'Toggle')
    assert dev(DI, '1_03').mode == 'Simple'
    assert 'ds_mode' in dev(DI, '1_01').full()
    assert 'ds_mode' not in dev(DI, '1_03').full()


async def test_di_set_direct_switch_keeps_other_bits(unit):
    client = await unit({1014: 0b1000, 1015: 0b0010, 1016: 0b0010})
    di = dev(DI, '1_02')
    await di.set(mode='DirectSwitch', ds_mode='Inverted')
    assert client.mb_client.holding[1014] == 0b1010
    assert client.mb_client.holding[1015] == 0b0010
    assert client.mb_client.holding[1016] == 0b0000
    # cache is updated, so the next scan does not flip the mode back
    await di.check_new_data()
    assert (di.mode, di.ds_mode) == ('DirectSwitch', 'Inverted')

    await di.set(mode='Simple')
    assert client.mb_client.holding[1014] == 0b1000


async def test_di_set_counter_and_debounce(unit):
    client = await unit()
    di = dev(DI, '1_02')
    await di.set(counter='70000', debounce='12.0')
    assert ('regs', 15, [70000 & 0xffff, 70000 >> 16]) in client.mb_client.writes   # low word first
    assert client.mb_client.holding[1011] == 12
    # cache is updated, the new values are seen without a scan
    await di.check_new_data()
    assert (di.counter, di.debounce) == (70000, 12)


async def test_di_counter_mode_disabled_zeroes_counter(unit):
    await unit({13: 5})
    di = dev(DI, '1_01')
    await di.set(counter_mode='Disabled')
    assert di.full()['counter'] == 0


# --- DigitalOutput (hard PWM) -----------------------------------------------

async def test_do_value_and_pwm_from_registers(unit):
    # cycle 48000, prescale 10 -> 100 Hz, duty 12000/48000 -> 25 %
    await unit({1: 0b01, 1018: 47999, 1017: 9, 22: 12000})
    do1, do2 = dev(DO, '1_01'), dev(DO, '1_02')
    assert (do1.value, do1.mode, do1.pwm_duty) == (1, 'Simple', 0)
    assert (do2.value, do2.mode, do2.pwm_duty) == (0, 'PWM', 25.0)
    assert do1.pwm_freq == do2.pwm_freq == 100.0


async def test_do_set_value_writes_coil(unit):
    client = await unit()
    await dev(DO, '1_02').set(value='1')
    assert client.mb_client.writes == [('coil', 1, 1)]


async def test_do_set_value_and_duty_conflict(unit):
    await unit()
    with pytest.raises(Exception, match='conflict'):
        await dev(DO, '1_01').set(value=1, pwm_duty=50)


async def test_do_set_pwm_freq_updates_all_outputs(unit):
    client = await unit({1018: 47999, 1017: 9, 22: 24000})    # 1_02 at 50 %
    await dev(DO, '1_01').set(pwm_freq=100)
    # 48 MHz / 100 Hz = 480000 = 10000 * 48
    assert client.mb_client.holding[1018] == 9999
    assert client.mb_client.holding[1017] == 47
    # the other output keeps its duty cycle with the new period
    assert client.mb_client.holding[22] == 5000
    assert dev(DO, '1_02').pwm_freq == 100


async def test_do_set_pwm_duty(unit):
    client = await unit({1: 0b01, 1018: 9999, 1017: 47})
    do = dev(DO, '1_01')
    await do.set(pwm_duty=25)
    # PWM output is switched off as a coil first
    assert client.mb_client.writes == [('coil', 0, 0), ('reg', 21, 2500)]
    assert do.mode == 'PWM'


async def test_do_timeout_reverts_value(unit):
    client = await unit()
    do = dev(DO, '1_01')
    res = await do.set(value=1, timeout=0.01)
    assert res['pending'] is True
    await asyncio.sleep(0.05)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]
    assert do.pending_task is None


@pytest.mark.xfail(strict=True, reason="set() reports the cached state until the next scan")
async def test_do_set_returns_new_value(unit):
    await unit()
    res = await dev(DO, '1_01').set(value=1)
    assert res['value'] == 1


# --- AnalogInput ------------------------------------------------------------

async def test_ai_value_and_mode(unit):
    await unit({2: to_registers(FLOAT32_LE, 1.5)[0], 3: to_registers(FLOAT32_LE, 1.5)[1],
                1019: 1, 1020: 3})
    ai1, ai2 = dev(AI, '1_01'), dev(AI, '1_02')
    assert (ai1.value, ai1.mode, ai1.unit_name, ai1.range) == (1.5, 'Voltage', 'V', [0, 10])
    assert (ai2.mode, ai2.unit_name) == ('Current', 'mA')


async def test_ai_set_mode_writes_mode_register(unit):
    client = await unit()
    await dev(AI, '1_03').set(mode='Resistance')
    assert client.mb_client.holding[1021] == 4


AI_MODES = {
    'Scaled': {'value': 1, 'transformation': {'datatype': 'uint32', 'ratio': 2}},
    'Float': {'value': 2, 'transformation': {'datatype': 'float32', 'ratio': 0.5, 'decimals': 1}},
    'Raw': {'value': 3},
}


def make_ai(mode_value, regs):
    client = make_client([{'start_reg': 0, 'count': 3, 'frequency': 1}],
                         {0: regs[0], 1: regs[1], 2: mode_value})
    return client, AnalogInput('x', client, 0, regmode=2, modes=AI_MODES)


async def test_ai_transformation():
    client, ai = make_ai(1, [3, 1])
    await client.cache.do_scan(initial=True)
    await ai.check_new_data()
    assert (ai.mode, ai.value) == ('Scaled', (0x10003) * 2)

    f = to_registers(FLOAT32_LE, 3.0)
    client.mb_client.holding.update({0: f[0], 1: f[1], 2: 2})
    await client.cache.do_scan()
    await ai.check_new_data()
    assert (ai.mode, ai.value) == ('Float', 1.5)


async def test_ai_mode_without_transformation_uses_default():
    f = to_registers(FLOAT32_LE, 3.0)
    client, ai = make_ai(2, f)
    await client.cache.do_scan(initial=True)
    await ai.check_new_data()
    client.mb_client.holding[2] = 3
    await client.cache.do_scan()
    await ai.check_new_data()
    assert (ai.mode, ai.value) == ('Raw', 3.0)


@pytest.mark.parametrize('transformation, regs, expected', [
    ({}, to_registers(FLOAT32_LE, 1.23456), 1.235),                  # float32, 3 decimals
    ({'datatype': 'float32', 'ratio': 2}, to_registers(FLOAT32_LE, 1.23456), 2.469),
    ({'datatype': 'int32', 'ratio': 3}, [0xfffe, 0xffff], -6),
    ({'datatype': 'uint32', 'ratio': 0.0001}, [12345, 0], pytest.approx(1.2345)),  # no rounding
    ({'datatype': 'uint32', 'ratio': 0.001, 'decimals': 1}, [12345, 0], 12.3),
    ({'datatype': 'bogus'}, [1, 0], None),
])
async def test_ai_transformation_datatypes(transformation, regs, expected):
    client = make_client([{'start_reg': 0, 'count': 3, 'frequency': 1}],
                         {0: regs[0], 1: regs[1], 2: 1})
    ai = AnalogInput('x', client, 0, regmode=2, modes={'M': {'value': 1, 'transformation': transformation}})
    await client.cache.do_scan(initial=True)
    await ai.check_new_data()
    assert (ai.mode, ai.value) == ('M', expected)


async def test_ai_unknown_mode_reads_none():
    client, ai = make_ai(9, [1, 0])
    await client.cache.do_scan(initial=True)
    await ai.check_new_data()
    assert (ai.mode, ai.value) == (None, None)


# --- NvSave -----------------------------------------------------------------

@pytest.fixture
def nv_save(monkeypatch):
    monkeypatch.setattr(NvSave, 'HOLD_TIME', 0.01)
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1}])
    return client, NvSave('x', client, 5)


async def test_nv_save_holds_value_until_timeout(nv_save):
    client, nv = nv_save
    assert (await nv.set(value=0))['value'] == 0
    assert client.mb_client.writes == []
    assert (await nv.set(value='1'))['value'] == 1
    assert client.mb_client.writes == [('coil', 5, 1)]
    with pytest.raises(ValueError):
        await nv.set(value=1)
    assert client.mb_client.writes == [('coil', 5, 1)]
    await asyncio.sleep(0.03)
    assert nv.full()['value'] == 0
    await nv.set(value=1)
    assert client.mb_client.writes == [('coil', 5, 1), ('coil', 5, 1)]


async def test_nv_save_failed_write_releases_timer(nv_save):
    client, nv = nv_save

    async def fail(address, value):
        raise ConnectionError('no answer')
    client.mb_client.write_single_coil = fail
    with pytest.raises(ConnectionError):
        await nv.set(value=1)
    await asyncio.sleep(0)
    assert (nv.value, nv.hold_task) == (0, None)


# --- Watchdog, LED ----------------------------------------------------------

async def test_watchdog(unit):
    client = await unit({12: 0b111, 1008: 500})
    wd = dev(WATCHDOG, '1_01')
    assert (wd.value, wd.timeout, wd.was_wd_boot_value) == (3, 500, 1)
    await wd.set(value=0, timeout=70000)
    assert client.mb_client.holding[12] == 0
    assert client.mb_client.holding[1008] == 65535
    await wd.check_new_data()
    assert (wd.value, wd.timeout) == (0, 65535)


async def test_led(unit):
    client = await unit({3998: 0b101})
    assert [dev(LED, c).value for c in ('1_01', '1_02', '1_03')] == [1, 0, 1]
    await dev(LED, '1_02').set(value=1)
    assert client.mb_client.writes == [('coil', 3001, 1)]


# --- AnalogOutput -----------------------------------------------------------

async def test_analog_output_scaling_and_clamp():
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1}], {0: 2000})
    ao = AnalogOutput('x', client, 0, modes={'Voltage': {'value': 0, 'unit': 'V'}})
    await client.cache.do_scan(initial=True)
    await ao.check_new_data()
    assert (ao.value, ao.mode, ao.unit_name) == (5.0, 'Voltage', 'V')
    assert await ao.set_value(20) == 10.238
    assert client.mb_client.holding[0] == 4095
    assert await ao.set_value(-1) == 0
    assert await ao.set_value('1.23456') == 1.235     # rounded to the nearest step
    assert client.mb_client.holding[0] == 494


async def test_analog_output_mode_register():
    modes = {'Voltage': {'value': 0, 'unit': 'V', 'range': [0, 10]},
             'Current': {'value': 1, 'unit': 'mA', 'range': [0, 20]}}
    client = make_client([{'start_reg': 0, 'count': 2, 'frequency': 1}], {0: 0, 1: 1})
    ao = AnalogOutput('x', client, 0, regmode=1, modes=modes)
    assert (ao.mode, ao.unit_name, ao.range) == (None, None, None)
    await client.cache.do_scan(initial=True)
    await ao.check_new_data()
    assert (ao.mode, ao.unit_name, ao.range) == ('Current', 'mA', [0, 20])
    # an undefined mode must not keep the unit and range of the previous one
    client.mb_client.holding[1] = 7
    await client.cache.do_scan()
    assert await ao.check_new_data()
    assert (ao.mode, ao.unit_name, ao.range) == (None, None, None)


async def test_analog_without_modes():
    client = make_client([{'start_reg': 0, 'count': 2, 'frequency': 1}])
    assert AnalogOutput('x', client, 0).mode is None
    assert AnalogInput('x', client, 0).mode is None


async def test_analog_output_brain_float():
    f, r = to_registers(FLOAT32_LE, 2.5), to_registers(FLOAT32_LE, 100.0)
    client = make_client([{'start_reg': 0, 'count': 5, 'frequency': 1}],
                         {0: f[0], 1: f[1], 2: r[0], 3: r[1], 4: 3})
    ao = AnalogOutputBrain('x', client, 0, regmode=4, reg_res=2)
    await client.cache.do_scan(initial=True)
    await ao.check_new_data()
    assert (ao.mode, ao.full()['value']) == ('Resistance', 100.0)
    # the value cannot be set in Resistance mode
    with pytest.raises(ValueError):
        await ao.set(value=1.25)
    assert client.mb_client.writes == []
    await ao.set(mode='Voltage', value=1.25)
    assert client.mb_client.writes[-1] == ('regs', 0, to_registers(FLOAT32_LE, 1.25))
    with pytest.raises(ValueError):
        await ao.set(value=11)


async def test_analog_output_brain_set_value_unknown_mode():
    client = make_client([{'start_reg': 0, 'count': 5, 'frequency': 1}], {4: 7})
    ao = AnalogOutputBrain('x', client, 0, regmode=4, reg_res=2)
    await client.cache.do_scan(initial=True)
    await ao.check_new_data()
    assert ao.range is None
    with pytest.raises(ValueError):
        await ao.set_value(1.0)
    assert client.mb_client.writes == []


async def test_analog_output_brain_set_mode():
    f = to_registers(FLOAT32_LE, 2.5)
    client = make_client([{'start_reg': 0, 'count': 5, 'frequency': 1}],
                         {0: f[0], 1: f[1], 4: 0})
    ao = AnalogOutputBrain('x', client, 0, regmode=4, reg_res=2)
    await client.cache.do_scan(initial=True)
    await ao.check_new_data()
    res = await ao.set(mode='Current')
    # mode register is written, the value is reset to 0 in the new mode
    assert client.mb_client.writes == [('reg', 4, 1), ('regs', 0, to_registers(FLOAT32_LE, 0.0))]
    assert (res['mode'], res['unit']) == ('Current', 'mA')
    await ao.set(mode='Resistance')
    assert client.mb_client.holding[4] == 3
    assert ao.unit_name == 'Ohm'


# --- Register, DataPoint ----------------------------------------------------

async def test_register_holding_and_input():
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1},
                          {'start_reg': 0, 'count': 1, 'frequency': 1, 'type': 'input'}],
                         holding={0: 11}, inputs={0: 22})
    hreg = Register('h', client, 0)
    ireg = Register('i', client, 0, reg_type='input')
    assert hreg.full()['value'] is None          # not scanned yet
    await client.cache.do_scan(initial=True)
    assert await hreg.check_new_data() and await ireg.check_new_data()
    assert (hreg.full()['value'], ireg.full()['value']) == (11, 22)
    assert not await hreg.check_new_data()
    await hreg.set(value='5')
    assert client.mb_client.holding[0] == 5
    assert await hreg.check_new_data()            # cache is updated without a scan
    assert hreg.full() == {'dev': 'register', 'circuit': 'h', 'value': 5}
    with pytest.raises(ValueError, match='read-only'):
        await ireg.set(value=1)
    with pytest.raises(ValueError, match='out of range'):
        await hreg.set(value=-1)
    assert client.mb_client.writes == [('reg', 0, 5)]


def make_dp(regs, **kw):
    client = make_client([{'start_reg': 0, 'count': 3, 'frequency': 1}],
                         dict(enumerate(regs)))
    return client, DataPoint('x', client, 0, **kw)


async def test_data_point_float32_factor_offset():
    client, dp = make_dp(to_registers(FLOAT32_BE, 2.0), datatype='float32', factor=10, offset=1)
    await client.cache.do_scan(initial=True)
    await dp.check_new_data()
    assert dp.value == 21.0


async def test_data_point_nan():
    client, dp = make_dp(to_registers(FLOAT32_BE, math.nan), datatype='float32')
    await client.cache.do_scan(initial=True)
    await dp.check_new_data()
    assert dp.value == 'NaN'


async def test_data_point_read_only_without_valid():
    client, dp = make_dp([7])
    await client.cache.do_scan(initial=True)
    assert await dp.check_new_data()
    assert dp.full() == {'dev': 'data_point', 'circuit': 'x', 'value': 7}
    assert not await dp.check_new_data()
    with pytest.raises(ValueError, match='read-only'):
        await dp.set(value=1)
    assert client.mb_client.writes == []
    assert await dp.set() == {'dev': 'data_point', 'circuit': 'x', 'value': 7}


async def test_ow_temperature_valid_mask():
    client = make_client([{'start_reg': 0, 'count': 3, 'frequency': 1}], {0: 2150, 2: 0b10})
    t = OwTemperature('x', client, 0, 2, 0b10, factor=0.01, unit='C')
    assert await t.check_new_data()     # not scanned yet, is_valid None -> False
    assert (t.value, t.is_valid) == (None, False)
    assert t.is_valid is False
    await client.cache.do_scan(initial=True)
    assert await t.check_new_data()
    assert t.full() == {'dev': 'data_point', 'circuit': 'x', 'value': 21.5, 'unit': 'C', 'valid': True}
    # only the validity changes
    client.mb_client.holding[2] = 0b01
    await client.cache.do_scan()
    assert await t.check_new_data()
    assert (t.value, t.full()['valid']) == (21.5, False)
    assert not await t.check_new_data()


async def test_data_point_signed16():
    client, dp = make_dp([0xffff], datatype='signed16')
    await client.cache.do_scan(initial=True)
    await dp.check_new_data()
    assert dp.value == -1


@pytest.mark.parametrize('regs, kw, expected', [
    ([0xfffe], {}, -2),                                         # default is signed16
    ([0xfffe], {'datatype': 'int16', 'factor': 0.5, 'offset': 1}, 0.0),
    ([0xfffe], {'datatype': 'uint16'}, 0xfffe),
    ([0x1234, 0x5678], {'datatype': 'uint32'}, 0x12345678),     # high word first
    ([0xffff, 0xfffe], {'datatype': 'int32'}, -2),
])
async def test_data_point_datatypes(regs, kw, expected):
    client, dp = make_dp(regs, **kw)
    await client.cache.do_scan(initial=True)
    assert await dp.check_new_data()
    assert dp.value == expected


async def test_data_point_input_register():
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1, 'type': 'input'}],
                         inputs={0: 0xffff})
    dp = DataPoint('x', client, 0, reg_type='input')
    await client.cache.do_scan(initial=True)
    await dp.check_new_data()
    assert dp.value == -1


async def test_data_point_not_scanned_and_unknown_datatype(caplog):
    client, dp = make_dp([5])
    await dp.check_new_data()
    assert dp.value is None
    client, dp = make_dp([5], datatype='bogus')
    assert 'Unknown datatype "bogus"' in caplog.text
    await client.cache.do_scan(initial=True)
    await dp.check_new_data()
    assert dp.value is None


async def test_data_point_set_value():
    client, dp = make_dp([0, 0], datatype='float32', factor=10, offset=1, writable=True)
    await client.cache.do_scan(initial=True)
    await dp.set(value='21')
    assert client.mb_client.writes == [('regs', 0, to_registers(FLOAT32_BE, 2.0))]   # high word first
    assert await dp.check_new_data()               # cache is updated without a scan
    assert dp.value == 21.0


async def test_data_point_set_signed16():
    client, dp = make_dp([0], factor=0.1, writable=True)
    await client.cache.do_scan(initial=True)
    await dp.set(value=-12.3)
    assert client.mb_client.holding[0] == 0x10000 - 123
    with pytest.raises(ValueError, match='out of range'):
        await dp.set(value=4000)


async def test_data_point_input_is_read_only():
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1, 'type': 'input'}])
    dp = DataPoint('x', client, 0, reg_type='input', writable=True)
    with pytest.raises(ValueError, match='read-only'):
        await dp.set(value=1)
    assert client.mb_client.writes == []
