import pytest

from evok.devices import Aliases, Devices, DeviceNotFound, DI, RO


class FakeDevice:
    def __init__(self, devtype, circuit):
        self.devtype = devtype
        self.circuit = circuit
        self.alias = ''


@pytest.fixture
def devices():
    for devtype, circuit in ((DI, '1_01'), (DI, '1_02'), (RO, '1_01')):
        Devices[devtype][circuit] = FakeDevice(devtype, circuit)
    return Devices


@pytest.mark.parametrize('alias', ['kitchen', 'Light-2', 'a.b_c', '1'])
def test_valid_alias(devices, alias):
    devices.set_alias(alias, devices[DI]['1_01'])
    assert devices.by_name(DI, alias) is devices[DI]['1_01']


@pytest.mark.parametrize('alias', ['a b', ' ', '/', 'ž', 'a/b'])
def test_invalid_alias(devices, alias):
    with pytest.raises(ValueError, match='Invalid alias'):
        devices.set_alias(alias, devices[DI]['1_01'])
    assert devices[DI]['1_01'].alias == ''


def test_duplicate_alias(devices):
    devices.set_alias('kitchen', devices[DI]['1_01'])
    with pytest.raises(ValueError, match='Duplicate alias'):
        devices.set_alias('kitchen', devices[RO]['1_01'])
    assert devices.by_name(DI, 'kitchen') is devices[DI]['1_01']


def test_alias_cannot_be_circuit_of_same_devtype(devices):
    with pytest.raises(ValueError, match='is a circuit'):
        devices.set_alias('1_02', devices[DI]['1_01'])
    assert devices.by_name(DI, '1_02') is devices[DI]['1_02']


def test_alias_can_be_circuit_of_other_devtype(devices):
    devices.set_alias('1_02', devices[RO]['1_01'])
    assert devices.by_name(RO, '1_02') is devices[RO]['1_01']


def test_empty_alias_resets(devices):
    devices.set_alias('kitchen', devices[DI]['1_01'])
    devices.set_alias('', devices[DI]['1_01'])
    assert devices[DI]['1_01'].alias == ''
    assert 'kitchen' not in devices.aliases


def test_alias_is_found_by_altname(devices):
    devices.set_alias('kitchen', devices[DI]['1_01'])
    assert devices.by_name('input', 'kitchen') is devices[DI]['1_01']


def test_alias_of_other_devtype_is_not_found(devices):
    devices.set_alias('pump', devices[RO]['1_01'])
    with pytest.raises(DeviceNotFound):
        devices.by_name(DI, 'pump')


def test_aliases_instances_do_not_share_dicts():
    first = Aliases({'kitchen': {'devtype': 'di', 'circuit': '1_01'}})
    second = Aliases({})
    assert second.initial_dict == {}
    assert second.alias_dict is not first.alias_dict


def test_alias_of_unregistered_device_is_reserved(devices):
    devices.aliases.initial_dict['kitchen'] = {'devtype': DI, 'circuit': '2_01'}
    with pytest.raises(ValueError, match='belongs to di 2_01'):
        devices.set_alias('kitchen', devices[DI]['1_01'])
    assert devices.aliases.initial_dict['kitchen'] == {'devtype': DI, 'circuit': '2_01'}


def test_saved_alias_is_assigned_on_registration(devices):
    devices.aliases.initial_dict['kitchen'] = {'devtype': DI, 'circuit': '2_01'}
    device = FakeDevice(DI, '2_01')
    devices.register_device(DI, device)
    assert device.alias == 'kitchen'
    assert devices.by_name(DI, 'kitchen') is device
    assert 'kitchen' not in devices.aliases.initial_dict


@pytest.mark.parametrize('record, devtype', [
    ({'devtype': 1, 'circuit': '1_01'}, 'di'),            # old numeric devtype
    ({'devtype': '0', 'circuit': '1_01'}, 'ro'),
    ({'devtype': 'di', 'circuit': '1_01'}, 'di'),
    ({'devtype': 99, 'circuit': '1_01'}, 99),             # unknown number is kept
    ({'devtype': None, 'circuit': '1_01'}, None),         # version 1.0 without dev_type
    ({'circuit': '1_01'}, None),
])
def test_load_aliases(record, devtype):
    aliases = Aliases({'a': record})
    assert aliases.initial_dict['a'].get('devtype') == devtype


def test_load_aliases_skips_invalid_record():
    aliases = Aliases({'a': 'di_1_01', 'b': {'devtype': 'di', 'circuit': '1_01'}})
    assert list(aliases.initial_dict) == ['b']


async def test_delete_alias_of_unregistered_device(devices):
    devices.aliases.initial_dict['kitchen'] = {'devtype': DI, 'circuit': '2_01'}
    await devices.aliases.set(delete='kitchen')
    assert 'kitchen' not in devices.aliases.get_dict_to_save()
    devices.set_alias('kitchen', devices[DI]['1_01'])
    assert devices.by_name(DI, 'kitchen') is devices[DI]['1_01']


async def test_delete_alias_of_registered_device(devices):
    devices.set_alias('kitchen', devices[DI]['1_01'])
    await devices.aliases.set(delete='kitchen')
    assert devices[DI]['1_01'].alias == ''
    with pytest.raises(DeviceNotFound):
        devices.by_name(DI, 'kitchen')


async def test_delete_unknown_alias(devices):
    with pytest.raises(ValueError, match='Unknown alias'):
        await devices.aliases.set(delete='kitchen')


def test_none_alias_resets_to_empty_string(devices):
    devices.set_alias('kitchen', devices[DI]['1_01'])
    devices.set_alias(None, devices[DI]['1_01'])
    assert devices[DI]['1_01'].alias == ''
    assert 'kitchen' not in devices.aliases



@pytest.mark.parametrize('find', [
    lambda: Devices.by_name('foo'),
    lambda: Devices.by_name('foo', '1_01'),
])
def test_unknown_devtype(find):
    with pytest.raises(DeviceNotFound, match="Invalid device type 'foo'"):
        find()


def test_by_name_major_group(devices):
    devices[DI]['1_01'].major_group = '1'
    devices[DI]['1_02'].major_group = '2'
    assert devices.by_name(DI, major_group='2') == [devices[DI]['1_02']]
    assert devices.by_name('input', major_group='3') == []
    assert list(devices.by_name(DI)) == [devices[DI]['1_01'], devices[DI]['1_02']]
