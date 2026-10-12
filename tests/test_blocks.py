import asyncio

import pytest

from evok import devents
from evok.blocks import Sequence, Sequencer, Step, pulse, pulse_params, sequencer
from evok.devices import DO, LED, RO


class FakeDevice:
    """ A device without a Modbus unit, its changes are recorded """
    def __init__(self, devtype=RO, circuit='1_01'):
        self.devtype = devtype
        self.circuit = circuit
        self.changes = []

    async def set(self, **kw):
        if kw.get('value') == 'fail':
            raise ConnectionError('lost')
        self.changes.append(kw)


@pytest.fixture
def events(monkeypatch):
    sent = []
    monkeypatch.setattr(devents, 'status', lambda device, **kw: sent.append(device))
    return sent


async def test_sequence_sets_its_steps(events):
    device = FakeDevice()
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 1}), Step({'value': 0}, 0.01), Step({'value': 1}, 0.01)]))
    assert seq.is_running(device)
    await asyncio.sleep(0.05)
    assert device.changes == [{'value': 1}, {'value': 0}, {'value': 1}]
    assert not seq.is_running(device)
    assert events == [device] * 3                           # a device without a unit sends its event


async def test_new_sequence_replaces_the_running_one():
    device = FakeDevice()
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 1}, 0.01)]))
    seq.start(device, Sequence([Step({'value': 0}, 0.01)]))
    await asyncio.sleep(0.05)
    assert device.changes == [{'value': 0}]


async def test_cancel_has_no_final_state():
    device = FakeDevice()
    seq = Sequencer()
    seq.start(device, pulse(1, 0.01))
    seq.cancel(device)
    await seq.finish_all()
    await asyncio.sleep(0.03)
    assert device.changes == [] and not seq.is_running(device)


async def test_finish_all_writes_the_final_states():
    first, second = FakeDevice(circuit='1_01'), FakeDevice(circuit='1_02')
    seq = Sequencer()
    seq.start(first, pulse(1, 10))
    seq.start(second, Sequence([Step({'value': 1}, 10)]))     # without a final state
    await seq.finish_all()
    await asyncio.sleep(0.01)
    assert (first.changes, second.changes) == ([{'value': 0}], [])
    assert not seq.is_running(first) and not seq.is_running(second)


async def test_failed_step_ends_the_sequence(caplog):
    device = FakeDevice(DO, '2_01')
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 'fail'}), Step({'value': 1}, 0.01)], name='test'))
    await asyncio.sleep(0.03)
    assert device.changes == [] and not seq.is_running(device)
    assert 'DO 2_01: step 1 of the test failed' in caplog.text


def test_global_sequencer():
    assert isinstance(sequencer, Sequencer)


@pytest.mark.parametrize('devtype, kw, params, duration, end', [
    (RO, {'value': 1, 'pulse_duration': '0.5'}, {'value': 1}, 0.5, 0),
    (LED, {'value': '0', 'pulse_duration': 2, 'alias': 'x'}, {'value': '0', 'alias': 'x'}, 2.0, 1),
    (DO, {'value': True, 'timeout': 1}, {'value': True}, 1.0, 0),       # the deprecated alias of a DO
    (DO, {'value': 1, 'timeout': None}, {'value': 1}, None, None),
    (RO, {'value': 1}, {'value': 1}, None, None),
])
def test_pulse_params(devtype, kw, params, duration, end):
    split, sequence = pulse_params(FakeDevice(devtype), kw)
    assert split == params
    if duration is None:
        assert sequence is None
    else:
        assert (sequence.steps[0].delay, sequence.steps[0].params, sequence.final) == (duration, {'value': end},
                                                                                       {'value': end})


@pytest.mark.parametrize('devtype, kw, error', [
    (RO, {'pulse_duration': 1}, 'pulse_duration requires value'),
    (RO, {'value': 1, 'pulse_duration': 0}, 'must be positive'),
    (RO, {'value': 1, 'pulse_duration': 'nan'}, None),
    (RO, {'value': '2', 'pulse_duration': 1}, None),
    (DO, {'value': 1, 'pulse_duration': 1, 'timeout': 1}, 'timeout is a deprecated alias of pulse_duration'),
])
def test_pulse_params_invalid(devtype, kw, error):
    with pytest.raises(ValueError, match=error):
        pulse_params(FakeDevice(devtype), kw)


def test_timeout_is_not_an_alias_of_other_devices():
    """ timeout of a watchdog is its own param """
    assert pulse_params(FakeDevice('watchdog'), {'timeout': 5000}) == ({'timeout': 5000}, None)
