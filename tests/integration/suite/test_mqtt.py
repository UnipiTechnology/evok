"""The MQTT API: the retained states, the commands, the errors and the Home Assistant discovery.

Runs with ``EVOK_MQTT=<host>:<port>``, the broker of the MQTT API of the server, with the
prefix ``evok`` and ``ha_discovery: true`` (the launcher of the mockbus starts the broker and
configures evok so, see mockbus/config.py). See docs/apis/mqtt.md.
"""

import asyncio
import json
import os

import pytest
from amqtt.client import MQTTClient
from tests.integration.clients.http import validate_states

BROKER = os.environ.get("EVOK_MQTT")
PREFIX = "evok"
RELAY = "2_03"

pytestmark = pytest.mark.skipif(not BROKER, reason="set EVOK_MQTT=<host>:<port> of the broker")


@pytest.fixture
async def mqtt():
    client = MQTTClient()
    await client.connect(f"mqtt://{BROKER}/")
    yield client
    await client.disconnect()


async def _collect(client: MQTTClient, seconds: float, until=None) -> dict[str, bytes]:
    """The last payload of each topic received for the time, or until the condition holds"""
    received: dict[str, bytes] = {}
    end = asyncio.get_running_loop().time() + seconds
    while (left := end - asyncio.get_running_loop().time()) > 0:
        try:
            message = await asyncio.wait_for(client.deliver_message(), left)
        except TimeoutError:
            break
        received[message.topic] = bytes(message.data)
        if until is not None and until(message.topic, bytes(message.data)):
            break
    return received


def _state(payload: bytes) -> dict:
    state = json.loads(payload)
    validate_states("MQTT", state)
    return state


async def test_status_and_retained_states(mqtt):
    await mqtt.subscribe([(f"{PREFIX}/#", 0)])
    received = await _collect(mqtt, 2.0)
    assert received.get(f"{PREFIX}/status") == b"online", sorted(received)
    states = {
        topic: _state(payload) for topic, payload in received.items() if topic.count("/") == 2
    }
    assert f"{PREFIX}/ro/{RELAY}" in states, sorted(received)
    assert f"{PREFIX}/temp/28CD79A90800004A" in states or any("/sensor/" in t for t in states)
    assert not any(topic.startswith(f"{PREFIX}/run/") for topic in states)


@pytest.mark.parametrize("payload, value", [(b"1", 1), (b'{"value": 0}', 0)])
async def test_command_changes_the_state(mqtt, http, payload, value):
    topic = f"{PREFIX}/ro/{RELAY}"
    # amqtt delivers the new messages only to the subscription of '#', not of the exact topic or '+'
    # the opposite value first, a state is published only after a change
    http.post_form(f"/rest/ro/{RELAY}/", {"value": str(1 - value)})
    await mqtt.subscribe([(f"{PREFIX}/#", 0)])
    await _collect(mqtt, 1.5)  # the retained states and the change by REST
    await mqtt.publish(f"{topic}/set", payload)
    received = await _collect(
        mqtt, 3.0, until=lambda t, p: t == topic and json.loads(p)["value"] == value
    )
    assert _state(received[topic])["value"] == value
    assert http.get(f"/rest/ro/{RELAY}/").body["value"] == value


@pytest.mark.parametrize(
    "topic, payload, error",
    [
        (f"{PREFIX}/ro/9_99/set", b"1", "DeviceNotFound"),
        (f"{PREFIX}/ro/{RELAY}/set", b'{"bogus": 1}', "ValidationError"),
    ],
)
async def test_command_error(mqtt, topic, payload, error):
    await mqtt.subscribe([(f"{PREFIX}/#", 0)])
    await mqtt.publish(topic, payload)
    received = await _collect(mqtt, 3.0, until=lambda t, p: t == f"{PREFIX}/error")
    reply = json.loads(received[f"{PREFIX}/error"])
    assert reply["topic"] == topic
    assert reply["success"] is False
    assert error in reply["errors"], reply


async def test_home_assistant_discovery(mqtt):
    await mqtt.subscribe([("homeassistant/#", 0)])
    received = await _collect(mqtt, 2.0)
    configs = [json.loads(p) for t, p in received.items() if t.endswith("/config") and p]
    assert configs, sorted(received)
    relay = [c for c in configs if c.get("state_topic") == f"{PREFIX}/ro/{RELAY}"]
    assert relay, [c.get("state_topic") for c in configs]
    assert relay[0]["command_topic"] == f"{PREFIX}/ro/{RELAY}/set"
    assert relay[0]["availability"] or relay[0].get("availability_topic")
