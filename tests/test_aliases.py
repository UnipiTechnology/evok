import pytest

from evok.devices import Devices, DI, RO


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
