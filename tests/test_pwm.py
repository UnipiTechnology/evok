import pytest

from evok.modbus.pwm import HardPwmFrequency, SoftPwmFrequency

from conftest import make_client


async def make_pwm(cls, holding):
    client = make_client([{'start_reg': 0, 'count': 2, 'frequency': 1}], holding)
    await client.cache.do_scan(initial=True)
    return client, cls(client, 0, 1)


async def test_hard_update_and_duty():
    # cycle 48000, prescale 10 -> 100 Hz
    client, pwm = await make_pwm(HardPwmFrequency, {0: 47999, 1: 9})
    assert pwm.update()
    assert pwm.freq == 100.0
    assert not pwm.update()
    assert (pwm.duty(12000), pwm.duty_raw(25)) == (25.0, 12000)


@pytest.mark.parametrize('freq, cycle, prescale', [
    (100, 60000, 8),        # the smallest prescale, the longest cycle
    (960, 50000, 1),
    (1000, 48000, 1),       # was 1000 * 48
    (7, 65306, 105),        # was 2619 * 2619
    (20000, 2400, 1),       # was 49 * 49, 19991.7 Hz with the duty by 2 %
    (50000, 960, 1),
])
def test_hard_divide(freq, cycle, prescale):
    assert HardPwmFrequency.divide(freq) == (cycle, prescale)
    assert HardPwmFrequency.frequency(cycle, prescale) == freq


async def test_hard_set_writes_registers_and_cache():
    client, pwm = await make_pwm(HardPwmFrequency, {0: 47999, 1: 9})
    pwm.update()
    await pwm.set(100)
    assert client.mb_client.writes == [('regs', 0, [59999, 7])]    # the adjacent registers by one request
    assert (pwm.freq, pwm.cycle) == (100.0, 60000)
    # cache is updated, the next update sees the same frequency
    assert not pwm.update()


@pytest.mark.parametrize('freq', [1e9, 100000, 50000.1, 0.001])
def test_hard_divide_out_of_range(freq):
    # up to 192 MHz was the cycle 1, the duty only 0 or 100 %
    with pytest.raises(ValueError, match='out of range'):
        HardPwmFrequency.divide(freq)


async def test_hard_frequency_is_rounded():
    client, pwm = await make_pwm(HardPwmFrequency, {0: 1454, 1: 0})    # 48 MHz / 1455
    pwm.update()
    assert pwm.freq == 32989.7
    pwm = HardPwmFrequency(client, 0, 1)
    client.cache.set_register(0, [65535, 65394])                       # the slowest timer
    pwm.update()
    assert pwm.freq == 0.0112                                           # not 0 by 0.1 Hz


async def test_write_of_registers_not_adjacent():
    client = make_client([{'start_reg': 0, 'count': 4, 'frequency': 1}], {})
    await client.cache.do_scan(initial=True)
    pwm = HardPwmFrequency(client, 0, 2)
    await pwm.set(100)
    assert client.mb_client.writes == [('reg', 0, 59999), ('reg', 2, 7)]


@pytest.mark.parametrize('preset, prescale, freq', [(0, 5, 1000), (1, 5, 100), (2, 4, 200.0)])
async def test_soft_update(preset, prescale, freq):
    client, pwm = await make_pwm(SoftPwmFrequency, {0: preset, 1: prescale})
    assert pwm.update()
    assert pwm.freq == freq


async def test_soft_set_preset_and_custom():
    client, pwm = await make_pwm(SoftPwmFrequency, {0: 0})
    pwm.update()
    await pwm.set(100)
    assert client.mb_client.writes == [('reg', 0, 1)]
    assert pwm.freq == 100 and not pwm.update()
    await pwm.set(300)
    assert client.mb_client.writes[-1] == ('regs', 0, [2, 2])
    assert pwm.freq == 333.3 and not pwm.update()
    with pytest.raises(ValueError):
        await pwm.set(5000)
    assert (pwm.duty(40), pwm.duty_raw(40.4)) == (40, 40)
