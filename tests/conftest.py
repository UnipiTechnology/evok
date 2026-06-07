import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── async helpers ─────────────────────────────────────────────────────────────

class AsyncIter:
    """Turn a plain list into an async iterator (simulates aiomqtt message stream)."""
    def __init__(self, items):
        self._items = list(items)
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


class FakeMqttInner:
    """Simulates the object returned by `async with aiomqtt.Client() as client`."""
    def __init__(self, messages=None):
        self.published = []
        self.subscribed = []
        self._messages = messages or []

    async def publish(self, topic, payload, retain=False):
        self.published.append({'topic': topic, 'payload': payload, 'retain': retain})

    async def subscribe(self, topic):
        self.subscribed.append(topic)

    @property
    def messages(self):
        return AsyncIter(self._messages)


class FakeMqttClient:
    """Simulates aiomqtt.Client used as async context manager."""
    def __init__(self, inner=None):
        self.inner = inner or FakeMqttInner()
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self.inner

    async def __aexit__(self, *args):
        pass


# ── device fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_device():
    device = MagicMock()
    device.devtype = 'di'
    device.circuit = '1_01'
    device.full.return_value = {'dev': 'di', 'circuit': '1_01', 'value': 0}
    device.set = AsyncMock(return_value={'dev': 'di', 'circuit': '1_01', 'value': 1})
    # no changeset — single device
    del device.changeset
    return device


@pytest.fixture
def fake_device_with_changeset():
    dev_a = MagicMock()
    dev_a.devtype = 'di'
    dev_a.circuit = '1_01'
    dev_a.full.return_value = {'dev': 'di', 'circuit': '1_01', 'value': 0}

    dev_b = MagicMock()
    dev_b.devtype = 'ro'
    dev_b.circuit = '1_01'
    dev_b.full.return_value = {'dev': 'ro', 'circuit': '1_01', 'value': 1}

    container = MagicMock()
    container.changeset = [dev_a, dev_b]
    return container
