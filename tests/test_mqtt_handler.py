import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import FakeMqttClient, FakeMqttInner
from evok.mqtt_client import ConfigurationStructure


CONF = {
    'address': 'localhost',
    'port': 1883,
    'client-id': 'evok-test',
    'keepalive': 60,
    'qos': 0,
}


def make_handler(inner=None):
    from evok.handler_mqtt import MqttHandler
    from tornado.ioloop import IOLoop
    inner = inner or FakeMqttInner()
    fake_client_ctx = FakeMqttClient(inner)
    loop = IOLoop.current()
    handler = MqttHandler(conf_data=CONF, loop=loop)
    handler._MqttHandler__client._MqttClient__client = fake_client_ctx
    return handler, inner


# ── on_event: single device ────────────────────────────────────────────────────

async def test_on_event_publishes_correct_topic(fake_device):
    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    handler.on_event(fake_device)
    await asyncio.sleep(0.05)  # let ensure_future run

    assert len(inner.published) == 1
    assert inner.published[0]['topic'] == 'evok-test/event/di/1_01'


async def test_on_event_publishes_device_full_data(fake_device):
    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    handler.on_event(fake_device)
    await asyncio.sleep(0.05)

    payload = json.loads(inner.published[0]['payload'])
    assert payload == fake_device.full.return_value


async def test_on_event_changeset_publishes_all_devices(fake_device_with_changeset):
    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    handler.on_event(fake_device_with_changeset)
    await asyncio.sleep(0.05)

    assert len(inner.published) == 2
    topics = {p['topic'] for p in inner.published}
    assert 'evok-test/event/di/1_01' in topics
    assert 'evok-test/event/ro/2_01' in topics


async def test_on_event_closure_captures_correct_values():
    """Each device in a changeset must publish to its own topic, not the last one."""
    devA = MagicMock()
    devA.devtype = 'di'
    devA.circuit = '1_01'
    devA.full.return_value = {'dev': 'di', 'circuit': '1_01', 'value': 0}

    devB = MagicMock()
    devB.devtype = 'ro'
    devB.circuit = '2_01'
    devB.full.return_value = {'dev': 'ro', 'circuit': '2_01', 'value': 1}

    container = MagicMock()
    container.changeset = [devA, devB]

    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    handler.on_event(container)
    await asyncio.sleep(0.05)

    published_topics = [p['topic'] for p in inner.published]
    assert 'evok-test/event/di/1_01' in published_topics
    assert 'evok-test/event/ro/2_01' in published_topics
    # If closure bug exists, both would have the same topic
    assert published_topics.count('evok-test/event/di/1_01') == 1
    assert published_topics.count('evok-test/event/ro/2_01') == 1


# ── on_message: device set ─────────────────────────────────────────────────────

async def test_on_message_sets_device_value(fake_device):
    handler, inner = make_handler()

    with patch('evok.handler_mqtt.Devices') as mock_devs, \
         patch('evok.handler_mqtt.schemas', {'di': ({}, {})}), \
         patch('evok.handler_mqtt.jsonschema'):
        mock_devs.by_name.return_value = fake_device
        await handler.on_message('evok-test/cmd/di/1_01', {'value': 1})

    fake_device.set.assert_awaited_once_with(value=1)


async def test_on_message_logs_error_on_unknown_device():
    handler, inner = make_handler()

    from evok.errors import DeviceNotFound
    with patch('evok.handler_mqtt.Devices') as mock_devs:
        mock_devs.by_name.side_effect = DeviceNotFound('not found')
        # Should not raise — just log
        await handler.on_message('evok-test/cmd/di/99_99', {'value': 1})


# ── on_message: ALL command ────────────────────────────────────────────────────

async def test_on_message_all_returns_all_devices():
    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    di_dev = MagicMock()
    di_dev.full.return_value = {'dev': 'di', 'circuit': '1_01', 'value': 0}

    with patch('evok.handler_mqtt.Devices') as mock_devs, \
         patch('evok.handler_mqtt.num_to_devtype_name', {1: 'di'}):
        mock_devs.by_int.return_value = [di_dev]
        await handler.on_message('evok-test/cmd/ALL', {})

    await asyncio.sleep(0.05)
    assert len(inner.published) == 1
    payload = json.loads(inner.published[0]['payload'])
    assert isinstance(payload, list)
    assert {'dev': 'di', 'circuit': '1_01', 'value': 0} in payload


async def test_on_message_all_topic_case_insensitive():
    handler, inner = make_handler()
    handler._MqttHandler__client.is_connected = True

    with patch('evok.handler_mqtt.Devices') as mock_devs, \
         patch('evok.handler_mqtt.num_to_devtype_name', {}):
        mock_devs.by_int.return_value = []
        # 'all' (lowercase) must also work
        await handler.on_message('evok-test/cmd/all', {})

    await asyncio.sleep(0.05)
    assert len(inner.published) == 1
