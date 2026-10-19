"""The webhook: Evok posts the changed states to its address.

Runs with ``EVOK_WEBHOOK_CONFIGURED=1`` against a server whose webhook is the receiver of the
tests (``http://127.0.0.1:<EVOK_WEBHOOK_PORT>/``, 8181 by default) with ``complex_events: true``
and ``device_mask: ["do"]`` — the configuration of the mockbus (mockbus/config.py). Without
``complex_events`` Evok sends an empty GET, see docs/apis/webhook.md.
"""

import asyncio
import os

import pytest
from tests.integration.clients.http import validate_states

pytestmark = pytest.mark.skipif(
    os.environ.get("EVOK_WEBHOOK_CONFIGURED") != "1",
    reason="the webhook of the server must post to the receiver; set EVOK_WEBHOOK_CONFIGURED=1",
)


async def _wait_for(capture, condition, seconds: float = 3.0) -> list[dict]:
    """The states of the received POSTs once the condition holds for one of them"""
    end = asyncio.get_running_loop().time() + seconds
    while True:
        states = [s for post in capture.posts for s in (post["body"] or []) if isinstance(s, dict)]
        if any(condition(s) for s in states) or asyncio.get_running_loop().time() > end:
            return states
        await asyncio.sleep(0.1)


async def test_change_is_posted(http, webhook_receiver):
    http.post_form("/rest/do/1_04/", {"value": "0"})
    webhook_receiver.capture.reset()
    http.post_form("/rest/do/1_04/", {"value": "1"})
    states = await _wait_for(
        webhook_receiver.capture, lambda s: s.get("circuit") == "1_04" and s.get("value") == 1
    )
    http.post_form("/rest/do/1_04/", {"value": "0"})
    changed = [s for s in states if s.get("dev") == "do" and s.get("circuit") == "1_04"]
    assert changed and changed[-1]["value"] == 1, webhook_receiver.capture.posts
    validate_states("webhook", states)


async def test_only_the_masked_device_types(http, webhook_receiver):
    webhook_receiver.capture.reset()
    http.post_form("/rest/ro/2_04/", {"value": "1"})
    http.post_form("/rest/do/1_04/", {"value": "1"})
    states = await _wait_for(webhook_receiver.capture, lambda s: s.get("circuit") == "1_04")
    http.post_form("/rest/ro/2_04/", {"value": "0"})
    http.post_form("/rest/do/1_04/", {"value": "0"})
    assert states, webhook_receiver.capture.posts
    assert {s["dev"] for s in states} == {"do"}, states
