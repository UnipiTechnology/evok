import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tests.conftest import FakeMqttClient, FakeMqttInner


from evok.mqtt_client import ConfigurationStructure, MqttClient


@pytest.fixture
def conf():
    return ConfigurationStructure(hostname='localhost', port=1883)


# ── send_to ────────────────────────────────────────────────────────────────────

async def test_send_to_publishes_when_connected(conf):
    inner = FakeMqttInner()
    client = MqttClient(conf=conf, callback=AsyncMock(), topic='t/#', client_id='test')
    client.is_connected = True
    client._MqttClient__client = FakeMqttClient(inner)

    await client.send_to('t/out', {'value': 1})

    assert inner.published == [{'topic': 't/out', 'payload': json.dumps({'value': 1}), 'retain': False}]


async def test_send_to_queues_when_disconnected(conf):
    client = MqttClient(conf=conf, callback=AsyncMock(), topic='t/#', client_id='test')
    # is_connected is False by default

    await client.send_to('t/out', {'value': 1})

    assert client.for_send == [{'topic': 't/out', 'data': {'value': 1}}]


async def test_send_to_queues_multiple_when_disconnected(conf):
    client = MqttClient(conf=conf, callback=AsyncMock(), topic='t/#', client_id='test')

    await client.send_to('t/a', {'v': 1})
    await client.send_to('t/b', {'v': 2})

    assert len(client.for_send) == 2
    assert client.for_send[0] == {'topic': 't/a', 'data': {'v': 1}}
    assert client.for_send[1] == {'topic': 't/b', 'data': {'v': 2}}


# ── run: pending messages are flushed after reconnect ─────────────────────────

async def test_run_flushes_pending_messages_on_connect(conf):
    inner = FakeMqttInner(messages=[])  # no incoming messages → loop ends via cancellation
    fake_client = FakeMqttClient(inner)

    client = MqttClient(conf=conf, callback=AsyncMock(), topic='t/#', client_id='test')
    # Queue a message before connecting
    client.for_send = [{'topic': 't/pending', 'data': {'x': 9}}]
    client._MqttClient__client = fake_client

    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)  # let run() complete one pass
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert any(p['topic'] == 't/pending' for p in inner.published), (
        "Pending message was not flushed after connect"
    )


# ── __on_message: callback invocation ─────────────────────────────────────────

async def test_on_message_invokes_callback(conf):
    callback = AsyncMock()
    client = MqttClient(conf=conf, callback=callback, topic='t/#', client_id='test')

    msg = MagicMock()
    msg.topic = 't/in'
    msg.payload = json.dumps({'v': 42}).encode()

    await client._MqttClient__on_message(msg)

    callback.assert_awaited_once_with('t/in', {'v': 42})


async def test_on_message_logs_error_on_invalid_json(conf):
    callback = AsyncMock()
    client = MqttClient(conf=conf, callback=callback, topic='t/#', client_id='test')

    msg = MagicMock()
    msg.topic = 't/in'
    msg.payload = b'not-valid-json'

    # Must not raise
    await client._MqttClient__on_message(msg)
    callback.assert_not_awaited()


# ── run: subscribes to correct topic ──────────────────────────────────────────

async def test_run_subscribes_to_configured_topic(conf):
    inner = FakeMqttInner(messages=[])
    fake_client = FakeMqttClient(inner)

    client = MqttClient(conf=conf, callback=AsyncMock(), topic='evok/cmd/#', client_id='test')
    client._MqttClient__client = fake_client

    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert 'evok/cmd/#' in inner.subscribed


async def test_run_delivers_message_to_callback(conf):
    callback = AsyncMock()

    msg = MagicMock()
    msg.topic = 'evok/cmd/di/1_01'
    msg.payload = json.dumps({'value': 1}).encode()

    inner = FakeMqttInner(messages=[msg])
    fake_client = FakeMqttClient(inner)

    client = MqttClient(conf=conf, callback=callback, topic='evok/cmd/#', client_id='test')
    client._MqttClient__client = fake_client

    task = asyncio.create_task(client.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    callback.assert_awaited_once_with('evok/cmd/di/1_01', {'value': 1})
