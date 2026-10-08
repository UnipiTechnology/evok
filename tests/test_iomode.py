import pytest

from evok.modbus.iomode import DIMode, IOMode

from conftest import make_client

MODES = {'Voltage': {'value': 0, 'unit': 'V', 'range': [0, 10]},
         'Current': {'value': 1, 'unit': 'mA', 'range': [0, 20]},
         'Fixed': {'unit': 'x'}}


async def make_iomode(mode_value, regmode=0, modes=MODES):
    client = make_client([{'start_reg': 0, 'count': 1, 'frequency': 1}], {0: mode_value})
    await client.cache.do_scan(initial=True)
    return client, IOMode(client, regmode, modes, 'AI x')


async def test_update_reports_change_once():
    client, iomode = await make_iomode(1)
    assert (iomode.mode, iomode.unit, iomode.range) == (None, None, None)
    assert iomode.update()
    assert (iomode.mode, iomode.mode_value, iomode.unit, iomode.range) == ('Current', 1, 'mA', [0, 20])
    assert not iomode.update()


async def test_undefined_mode_value():
    client, iomode = await make_iomode(7)
    assert iomode.update()
    assert (iomode.mode, iomode.mode_value, iomode.data) == (None, 7, {})


async def test_fixed_mode_without_register():
    client, iomode = await make_iomode(0, regmode=None, modes={'Voltage': MODES['Voltage']})
    assert iomode.mode == 'Voltage'
    assert not iomode.update()
    assert await iomode.set('Voltage') == MODES['Voltage']
    assert client.mb_client.writes == []


async def test_fixed_mode_without_value_and_register():
    client, iomode = await make_iomode(0, regmode=None, modes={'Fixed': MODES['Fixed']})
    assert iomode.mode == 'Fixed'
    assert await iomode.set('Fixed') == MODES['Fixed']
    assert client.mb_client.writes == []


async def test_set_writes_register_and_waits_for_scan():
    client, iomode = await make_iomode(0)
    iomode.update()
    assert await iomode.set('Current') == MODES['Current']
    assert client.mb_client.holding[0] == 1
    assert iomode.mode == 'Voltage'
    await client.cache.do_scan()
    assert iomode.update() and iomode.mode == 'Current'


async def test_set_invalid_mode():
    client, iomode = await make_iomode(0)
    with pytest.raises(ValueError):
        await iomode.set('Unknown')
    with pytest.raises(ValueError):
        await iomode.set('Fixed')
    assert client.mb_client.writes == []


async def make_dimode(holding, bitmask=0b10, modes=('Simple', 'DirectSwitch')):
    client = make_client([{'start_reg': 0, 'count': 3, 'frequency': 1}], holding)
    await client.cache.do_scan(initial=True)
    return client, DIMode(client, bitmask, 0, 1, 2, list(modes), ['Simple', 'Inverted', 'Toggle'], 'DI x')


async def test_dimode_update_reports_change_once():
    client, dimode = await make_dimode({0: 0b10, 1: 0, 2: 0b10})
    assert dimode.update()
    assert (dimode.mode, dimode.ds_mode) == ('DirectSwitch', 'Toggle')
    assert not dimode.update()


async def test_dimode_without_direct_switch_ignores_registers():
    client, dimode = await make_dimode({0: 0b10, 1: 0b10}, modes=('Simple',))
    assert not dimode.update()
    await dimode.set('Simple')
    assert (dimode.mode, dimode.ds_mode) == ('Simple', 'Simple')
    assert client.mb_client.writes == [('reg', 0, 0)]


@pytest.mark.parametrize('mode', [None, 'Simple'])
async def test_dimode_ds_mode_without_direct_switch_is_rejected(mode):
    """ ds_mode was ignored out of the DirectSwitch mode, the request succeeded without a write """
    client, dimode = await make_dimode({0: 0, 1: 0, 2: 0})
    dimode.update()
    with pytest.raises(ValueError, match='only in the DirectSwitch mode'):
        await dimode.set(mode, 'Inverted')
    assert client.mb_client.writes == []


async def test_dimode_ds_mode_is_written_before_mode():
    """ The input was switched to DirectSwitch with the old ds_mode, the output followed it for a moment """
    client, dimode = await make_dimode({0: 0, 1: 0, 2: 0})
    dimode.update()
    await dimode.set('DirectSwitch', 'Inverted')
    assert [w[1] for w in client.mb_client.writes] == [2, 1, 0]   # toggle cleared, polarity set, then mode


async def test_dimode_cleared_ds_bit_is_written_first():
    """ From Toggle to Inverted the polarity was set before the toggle was cleared """
    client, dimode = await make_dimode({0: 0b10, 1: 0, 2: 0b10})
    dimode.update()
    await dimode.set(ds_mode='Inverted')
    assert client.mb_client.writes == [('reg', 2, 0), ('reg', 1, 0b10)]
    assert (dimode.mode, dimode.ds_mode) == ('DirectSwitch', 'Inverted')


async def test_dimode_set_keeps_other_bits():
    client, dimode = await make_dimode({0: 0b01, 1: 0b01, 2: 0b11})
    await dimode.set('DirectSwitch', 'Inverted')
    assert [client.mb_client.holding[i] for i in range(3)] == [0b11, 0b11, 0b01]
    # cache is updated, so the next update does not flip the mode back
    assert not dimode.update()
    # unknown modes are rejected before anything is written
    writes = list(client.mb_client.writes)
    for mode, ds_mode in (('Unknown', None), ('DirectSwitch', 'Unknown')):
        with pytest.raises(ValueError, match='unknown'):
            await dimode.set(mode, ds_mode)
    assert (dimode.mode, dimode.ds_mode) == ('DirectSwitch', 'Inverted')
    assert client.mb_client.writes == writes
