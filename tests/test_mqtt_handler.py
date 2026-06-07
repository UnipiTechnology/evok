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
