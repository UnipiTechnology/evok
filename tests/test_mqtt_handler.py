import asyncio
import json
import logging

import aiomqtt
import pytest

from evok import mqtt_handler
from evok.devices import Devices, DI, RO
from evok.mqtt_handler import MqttHandler, MqttSettings
from evok.ws_handler import registered_ws


class FakeDevice:
    def __init__(self, devtype, circuit, value=0):
        self.devtype = devtype
        self.circuit = circuit
        self.value = value
        self.alias = ''
        self.calls = []

    def full(self):
        return {'dev': self.devtype, 'circuit': self.circuit, 'value': self.value}

    async def set(self, **kw):
        self.calls.append(kw)
        if 'value' in kw:
            self.value = kw['value']


class FakeClient:
    """ aiomqtt.Client recording the publishes, the messages are put by receive() """
    def __init__(self, broker, **kwargs):
        self.broker = broker
        self.kwargs = kwargs
        self.published = []
        self.subscribed = []
        self.queue = asyncio.Queue()

    async def __aenter__(self):
        if self.broker.failures:
            raise aiomqtt.MqttError(self.broker.failures.pop(0))
        self.broker.clients.append(self)
        return self

    async def __aexit__(self, *exc):
        return False

    async def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, retain))

    async def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    @property
    async def messages(self):
        while True:
            message = await self.queue.get()
            if message is None:
                raise aiomqtt.MqttError('Disconnected during message iteration')
            yield message


class FakeBroker:
    def __init__(self, failures=()):
        self.failures = list(failures)
        self.clients: list[FakeClient] = []

    def factory(self, **kwargs):
        return FakeClient(self, **kwargs)

    @property
    def client(self):
        return self.clients[-1]

    def receive(self, topic, payload):
        self.client.queue.put_nowait(aiomqtt.Message(topic, payload.encode(), 0, False, 0, None))

    def states(self):
        """ The published states by topic, the last one of each """
        return {topic: json.loads(payload) for topic, payload, _ in self.client.published
                if topic.count('/') == 2 and topic != 'evok/error'}

    def errors(self):
        return [json.loads(payload) for topic, payload, _ in self.client.published if topic == 'evok/error']


async def settle():
    for _ in range(20):
        await asyncio.sleep(0)


@pytest.fixture
def devices():
    Devices[DI]['1_01'] = FakeDevice(DI, '1_01', 1)
    Devices[RO]['1_01'] = FakeDevice(RO, '1_01')
    return Devices


@pytest.fixture
async def mqtt(devices, monkeypatch):
    """ A connected handler, call it with the options of the configuration """
    monkeypatch.setattr(mqtt_handler, 'RECONNECT_DELAY', 0)
    handlers = []

    async def factory(conf=None, failures=()):
        broker = FakeBroker(failures)
        handler = MqttHandler(MqttSettings(conf or {}), client_factory=broker.factory)
        handler.open()
        handlers.append(handler)
        for _ in range(100):
            if broker.clients:
                break
            await asyncio.sleep(0)
        await settle()
        return handler, broker
    yield factory
    for handler in handlers:
        await handler.stop()


def test_settings_defaults():
    settings = MqttSettings({'enabled': True})
    kw = settings.client_kwargs()
    assert (kw['hostname'], kw['port'], kw['username'], kw['tls_params']) == ('127.0.0.1', 1883, None, None)
    assert kw['identifier'].startswith('evok-')
    assert (kw['will'].topic, kw['will'].payload, kw['will'].retain) == ('evok/status', 'offline', True)
    assert (settings.prefix, settings.qos, settings.read_only) == ('evok', 0, False)
    assert 'run' not in settings.device_mask and {'di', 'sensor', 'watchdog'} <= settings.device_mask


def test_settings_tls():
    settings = MqttSettings({'ca_file': '/etc/ssl/ca.pem'})
    kw = settings.client_kwargs()
    assert (settings.tls, kw['port'], kw['tls_params'].ca_certs) == (True, 8883, '/etc/ssl/ca.pem')


@pytest.mark.parametrize('conf, error', [
    ({'hostname': ''}, "'hostname' must be a non-empty string"),
    ({'port': 0}, "'port' must be an integer"),
    ({'password': 'x'}, "'password' requires 'username'"),
    ({'prefix': 'evok/#'}, "'prefix' must be a topic"),
    ({'prefix': 'evok/'}, "'prefix' must be a topic"),
    ({'qos': 3}, "'qos' must be 0, 1 or 2"),
    ({'read_only': 'yes'}, "'read_only' must be true or false"),
    ({'device_mask': ['di', 'foo']}, "unknown device types in 'device_mask': ['foo']"),
    ({'device_mask': 'di'}, "'device_mask' must be a list"),
    ({'key_file': 'k.pem'}, "'key_file' requires 'cert_file'"),
    ({'hostnme': 'broker'}, "unknown options ['hostnme']"),
])
def test_settings_invalid(conf, error):
    with pytest.raises(ValueError, match=error.replace('[', r'\[').replace(']', r'\]')):
        MqttSettings(conf)


async def test_connection_publishes_online_and_all_states(mqtt):
    handler, broker = await mqtt()
    client = broker.client
    assert client.published[0] == ('evok/status', 'online', True)
    assert client.subscribed == ['evok/+/+/set']
    assert broker.states() == {'evok/di/1_01': {'dev': 'di', 'circuit': '1_01', 'value': 1},
                               'evok/ro/1_01': {'dev': 'ro', 'circuit': '1_01', 'value': 0}}
    assert all(retain for _, _, retain in client.published)
    assert handler in registered_ws['all']


async def test_event_publishes_the_changed_state(mqtt):
    handler, broker = await mqtt()
    di = Devices[DI]['1_01']
    di.value = 0
    handler.on_event(di)
    di.value = 1
    handler.on_event(di)            # merged with the previous change, the last state is published
    await settle()
    assert [json.loads(p)['value'] for t, p, _ in broker.client.published if t == 'evok/di/1_01'] == [1, 1]


async def test_device_mask(mqtt):
    handler, broker = await mqtt({'device_mask': ['input']})
    handler.on_event(Devices[RO]['1_01'])
    await settle()
    assert list(broker.states()) == ['evok/di/1_01']


@pytest.mark.parametrize('payload, expected', [
    ('{"value": 1}', {'value': 1}),
    ('1', {'value': 1}),
    ('true', {'value': True}),
    ('on', {'value': 'on'}),
    ('{"value": 1, "alias": "pump"}', {'value': 1, 'alias': 'pump'}),
])
async def test_set_command(mqtt, payload, expected):
    handler, broker = await mqtt()
    broker.receive('evok/ro/1_01/set', payload)
    await settle()
    assert Devices[RO]['1_01'].calls == [expected]
    assert broker.errors() == []


@pytest.mark.parametrize('topic, payload, error', [
    ('evok/ro/1_01/set', '{"value": 1, "foo": 2}', 'ValidationError'),
    ('evok/ro/9_99/set', '1', 'DeviceNotFound'),
    ('evok/foo/1_01/set', '1', 'DeviceNotFound'),
])
async def test_invalid_command_publishes_an_error(mqtt, caplog, topic, payload, error):
    handler, broker = await mqtt()
    broker.receive(topic, payload)
    await settle()
    assert Devices[RO]['1_01'].calls == []
    errors = broker.errors()
    assert len(errors) == 1 and errors[0]['topic'] == topic and errors[0]['success'] is False
    assert error in errors[0]['errors'] or error in json.dumps(errors[0]['errors'])
    assert f'MQTT {topic}' in caplog.text


async def test_read_only_does_not_subscribe(mqtt, caplog):
    caplog.set_level(logging.WARNING, logger='evok')
    handler, broker = await mqtt({'read_only': True})
    assert broker.client.subscribed == []
    assert 'accepted from any client' not in caplog.text


async def test_commands_without_a_user_are_warned(mqtt, caplog):
    await mqtt()
    assert 'the commands are accepted from any client of the broker 127.0.0.1:1883' in caplog.text


async def test_failed_connection_is_logged_once(mqtt, caplog):
    handler, broker = await mqtt(failures=['[Errno 111] Connection refused'] * 3)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and 'cannot connect to the broker 127.0.0.1:1883' in errors[0]
    assert broker.client.published[0] == ('evok/status', 'online', True)


async def test_lost_connection_publishes_all_states_again(mqtt, caplog):
    handler, broker = await mqtt()
    first = broker.client
    first.queue.put_nowait(None)                         # the broker disconnects
    for _ in range(100):
        if broker.client is not first:
            break
        await asyncio.sleep(0)
    await settle()
    assert broker.client is not first
    assert sorted(broker.states()) == ['evok/di/1_01', 'evok/ro/1_01']
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and 'the connection to the broker 127.0.0.1:1883 was lost' in errors[0]


async def test_stop_publishes_offline(mqtt):
    handler, broker = await mqtt()
    await handler.stop()
    assert broker.client.published[-1] == ('evok/status', 'offline', True)
    assert handler not in registered_ws['all']
    assert handler.task.done()


async def test_command_during_a_sequence_is_refused(mqtt):
    """ An output cannot be changed while its sequencer runs, the error is published """
    from evok.blocks import Sequence, Step, sequencer
    handler, broker = await mqtt()
    relay = Devices[RO]['1_01']
    sequencer.start(relay, Sequence([Step({'value': 0}, 10)]))
    broker.receive('evok/ro/1_01/set', '1')
    await settle()
    assert relay.calls == []
    errors = broker.errors()
    assert len(errors) == 1 and 'SequenceRunning' in errors[0]['errors']
