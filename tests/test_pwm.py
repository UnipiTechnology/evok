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
    (100, 10000, 48),       # 480000 = 10000 * 48, 50000 does not divide it
    (960, 50000, 1),
    (1000, 1000, 48),
    (7, 2619, 2619),        # no round cycle, sqrt split
])
def test_hard_divide(freq, cycle, prescale):
    assert HardPwmFrequency.divide(freq) == (cycle, prescale)


async def test_hard_set_writes_registers_and_cache():
    client, pwm = await make_pwm(HardPwmFrequency, {0: 47999, 1: 9})
    pwm.update()
    await pwm.set(100)
    assert (client.mb_client.holding[0], client.mb_client.holding[1]) == (9999, 47)
    assert (pwm.freq, pwm.cycle) == (100.0, 10000)
    # cache is updated, the next update sees the same frequency
    assert not pwm.update()


def test_hard_divide_out_of_range():
    with pytest.raises(ValueError):
        HardPwmFrequency.divide(1e9)
    with pytest.raises(ValueError):
        HardPwmFrequency.divide(0.001)


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
    assert (client.mb_client.holding[0], client.mb_client.holding[1]) == (2, 2)
    assert pwm.freq == 333.3 and not pwm.update()
    with pytest.raises(ValueError):
        await pwm.set(5000)
    assert (pwm.duty(40), pwm.duty_raw(40.4)) == (40, 40)
