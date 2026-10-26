import asyncio
import sys

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


async def test_failed_step_is_written_again(caplog, monkeypatch):
    """ A failed step ended the sequence, the end of a pulse was lost and the output stayed in its state """
    monkeypatch.setattr(sys.modules['evok.blocks.sequencer'], 'STEP_RETRY_DELAY', 0.01)
    device = FakeDevice(DO, '2_01')
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 'fail'}), Step({'value': 1}, 0.01)], name='test'))
    await asyncio.sleep(0.05)
    assert device.changes == [] and seq.is_running(device)
    assert caplog.text.count('DO 2_01: step 1 of the test failed') == 1      # logged once
    seq.cancel(device)
    await asyncio.sleep(0.03)
    assert not seq.is_running(device)


async def test_refused_step_ends_the_sequence(caplog, monkeypatch):
    """ A value refused by the device is not an error of the communication, it was written again forever and
        the output refused every change
    """
    monkeypatch.setattr(sys.modules['evok.blocks.sequencer'], 'STEP_RETRY_DELAY', 0.01)
    device = FakeDevice(DO, '2_01')

    async def refuse(**kw):
        raise ValueError('not in this mode')
    device.set = refuse
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 1})], name='test'))
    await asyncio.sleep(0.03)
    assert not seq.is_running(device)
    assert caplog.text.count('DO 2_01: step 1 of the test failed') == 1


async def test_step_is_done_after_its_write(monkeypatch):
    """ A step written again was reported as done, the end of a pulse seemed written while the relay was on """
    monkeypatch.setattr(sys.modules['evok.blocks.sequencer'], 'STEP_RETRY_DELAY', 0.01)
    device = FakeDevice(DO, '2_01')
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 'fail'}), Step({'value': 1})], name='test'))
    await asyncio.sleep(0.03)
    assert seq.running(device).step == 0
    seq.cancel(device)


async def test_last_step_ends_the_sequence_after_its_write(monkeypatch):
    monkeypatch.setattr(sys.modules['evok.blocks.sequencer'], 'STEP_RETRY_DELAY', 0.01)
    device = FakeDevice(DO, '2_01')
    failures = [ConnectionError('lost')] * 2
    set_ = device.set

    async def flaky(**kw):
        if failures:
            raise failures.pop()
        await set_(**kw)
    device.set = flaky
    seq = Sequencer()
    seq.start(device, Sequence([Step({'value': 0}, 0.01)], final={'value': 0}, name='pulse'))
    await asyncio.sleep(0.02)
    assert seq.is_running(device)                       # the end failed, it is written again
    await asyncio.sleep(0.05)
    assert device.changes == [{'value': 0}] and not seq.is_running(device)


def test_global_sequencer():
    assert isinstance(sequencer, Sequencer)


@pytest.mark.parametrize('devtype, kw, params, duration, end', [
    (RO, {'value': 1, 'pulse_duration': '0.5'}, {'value': 1}, 0.5, 0),
    (LED, {'value': '0', 'pulse_duration': 2, 'alias': 'x'}, {'value': '0', 'alias': 'x'}, 2.0, 1),
    (DO, {'value': True, 'pulse_duration': 1}, {'value': True}, 1.0, 0),
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
])
def test_pulse_params_invalid(devtype, kw, error):
    with pytest.raises(ValueError, match=error):
        pulse_params(FakeDevice(devtype), kw)


def test_timeout_is_not_an_alias():
    """ timeout of a DO is not an alias of pulse_duration anymore, only of the RPC method output_set_for_time """
    assert pulse_params(FakeDevice(DO), {'timeout': 5000}) == ({'timeout': 5000}, None)


# ---- the sequencer device of an output ----

from conftest import make_client, scan  # noqa: E402

from evok.devices import SEQUENCER, Devices  # noqa: E402
from evok.modbus import set_devices  # noqa: E402
from evok.modbus.builder import IOParser  # noqa: E402


@pytest.fixture
def unit(l0306):
    """ Populated L0306 unit '1' with the sequencer devices of its outputs """
    async def factory():
        client = make_client(l0306['modbus_register_blocks'])
        IOParser(client, l0306['modbus_features'], '1').populate()
        await scan(client, initial=True)
        return client
    return factory


async def test_builder_attaches_the_sequencers(unit):
    await unit()
    assert sorted(Devices[SEQUENCER]) == ['do_1_01', 'do_1_02', 'led_1_01', 'led_1_02', 'led_1_03']
    assert Devices[SEQUENCER]['do_1_01'].full() == {
        'dev': 'sequencer', 'circuit': 'do_1_01', 'output': {'dev': 'do', 'circuit': '1_01'},
        'running': False, 'name': None, 'step': None, 'steps': None}


async def test_pulse_by_the_sequencer(unit, events):
    client = await unit()
    seq = Devices[SEQUENCER]['do_1_01']
    state, = await set_devices([(seq, {'value': 1, 'pulse_duration': 0.02})])
    assert (state['running'], state['name'], state['step'], state['steps']) == (True, 'pulse', 0, 1)
    await asyncio.sleep(0.06)
    assert client.mb_client.writes == [('coil', 0, 1), ('coil', 0, 0)]
    assert seq.full()['running'] is False
    assert events.count(seq) == 2                           # the start and the end of the pulse


async def test_sequence_by_the_sequencer(unit):
    client = await unit()
    seq = Devices[SEQUENCER]['led_1_02']
    await set_devices([(seq, {'steps': [{'value': 1}, {'delay': 0.01, 'value': 0}, {'delay': 0.01, 'value': 1}],
                              'final': {'value': 0}})])
    assert seq.full()['steps'] == 3
    await asyncio.sleep(0.06)
    assert client.mb_client.writes == [('coil', 3001, 1), ('coil', 3001, 0), ('coil', 3001, 1)]
    assert seq.full()['running'] is False


async def test_cancel_by_the_sequencer(unit):
    client = await unit()
    seq = Devices[SEQUENCER]['do_1_02']
    await set_devices([(seq, {'value': 1, 'pulse_duration': 0.02})])
    await set_devices([(seq, {'cancel': True})])
    await asyncio.sleep(0.04)
    assert client.mb_client.writes == [('coil', 1, 1)]      # no end of the pulse
    assert seq.full()['running'] is False


async def test_change_of_the_output_is_refused_while_its_sequence_runs(unit, events):
    from evok.errors import SequenceRunning
    await unit()
    seq = Devices[SEQUENCER]['do_1_01']
    await set_devices([(seq, {'value': 1, 'pulse_duration': 1})])
    with pytest.raises(SequenceRunning):
        await set_devices([(seq.output, {'value': 0})])
    assert seq.full()['running'] is True
    await set_devices([(seq, {'cancel': True})])
    await set_devices([(seq.output, {'value': 0})])
    assert events.count(seq) == 2                           # the start and the cancel


@pytest.mark.parametrize('kw, error', [
    ({'value': 1}, 'value requires pulse_duration'),
    ({'pulse_duration': 1}, 'pulse_duration requires value'),
    ({'value': 1, 'pulse_duration': 1, 'steps': [{'value': 1}]}, 'set only one of pulse_duration and steps'),
    ({'steps': [{'value': 1}], 'cancel': True}, 'set only one of steps and cancel'),
    ({'final': {'value': 0}}, 'final requires steps'),
    ({'steps': []}, 'steps must be a list of 1..100 steps'),
    ({'steps': {'value': 1}}, 'steps must be a list'),
    ({'steps': [1]}, 'step 1 must be an object'),
    ({'steps': [{'delay': 1}]}, 'step 1 must change the output'),
    ({'steps': [{'alias': 'x'}]}, 'step 1 must change the output'),
    ({'steps': [{'value': 1, 'delay': -1}]}, 'must not be negative'),
    ({'steps': [{'value': 1}], 'final': {}}, 'final must be the params of the output'),
])
async def test_sequencer_rejects(unit, kw, error):
    client = await unit()
    seq = Devices[SEQUENCER]['do_1_01']
    with pytest.raises(ValueError, match=error):
        await set_devices([(seq, kw)])
    assert client.mb_client.writes == [] and seq.full()['running'] is False


async def test_steps_are_checked_by_the_schema_of_the_output(unit):
    import jsonschema
    client = await unit()
    with pytest.raises(jsonschema.ValidationError):
        await set_devices([(Devices[SEQUENCER]['do_1_01'], {'steps': [{'value': 1}, {'bogus': 1}]})])
    assert client.mb_client.writes == []


async def test_rpc_output_get_has_the_running_pulse(unit):
    from evok.rpc_handler import Handler
    await unit()
    handler = Handler.__new__(Handler)
    await handler.output_set_for_time('1_01', 1, 1)
    assert handler.output_get('1_01')[1] is True             # the fake unit does not map the coil to its register


async def test_every_step_sends_an_event(unit, monkeypatch):
    await unit()
    seq = Devices[SEQUENCER]['led_1_01']
    progress = []

    def record(device, **kw):
        if device is seq:
            progress.append((device.full()['running'], device.full()['step']))
    monkeypatch.setattr(devents, 'status', record)
    await set_devices([(seq, {'steps': [{'value': 1}, {'delay': 0.01, 'value': 0}, {'delay': 0.01, 'value': 1}]})])
    await asyncio.sleep(0.06)
    assert progress == [(True, 0), (True, 1), (True, 2), (False, None)]


async def test_rejected_request_does_not_change_the_alias(unit):
    await unit()
    seq = Devices[SEQUENCER]['do_1_01']
    with pytest.raises(ValueError):
        await set_devices([(seq, {'alias': 'pump', 'steps': []})])
    with pytest.raises(ValueError):
        await set_devices([(seq, {'alias': 'pump', 'value': 1, 'pulse_duration': 0})])
    assert seq.alias == ''


async def test_alias_of_the_sequencer_sends_an_event(unit, events):
    await unit()
    seq = Devices[SEQUENCER]['do_1_01']
    await set_devices([(seq, {'alias': 'pump_pulse'})])
    assert seq.full()['alias'] == 'pump_pulse' and events == [seq]
    assert Devices.by_name(SEQUENCER, 'pump_pulse') is seq


async def test_rpc_pending_is_only_a_pulse(unit):
    from evok.rpc_handler import Handler
    await unit()
    handler = Handler.__new__(Handler)
    await set_devices([(Devices[SEQUENCER]['do_1_01'], {'steps': [{'value': 1}, {'delay': 10, 'value': 0}]})])
    assert handler.output_get('1_01')[1] is False


async def test_rpc_change_during_a_pulse_is_refused(unit):
    from types import SimpleNamespace

    from evok.rpc_handler import Handler, SequenceRunningError, create_response
    await unit()
    await set_devices([(Devices[SEQUENCER]['do_1_01'], {'value': 1, 'pulse_duration': 10})])
    with pytest.raises(SequenceRunningError) as error:
        await create_response(SimpleNamespace(method='output_set', params=['1_01', 0]), Handler.__new__(Handler))
    assert error.value.error_code == -32002


async def test_rest_change_during_a_pulse_is_409(unit):
    from evok.errors import SequenceRunning
    from evok.handlers_base import client_error
    errors, status = client_error(SequenceRunning('DO 1_01: a sequence runs'))
    assert (errors, status) == ({'SequenceRunning': 'DO 1_01: a sequence runs'}, 409)
