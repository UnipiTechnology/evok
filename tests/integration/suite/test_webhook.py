"""Webhook outbound contract — INFERRED FROM CODE, NOT YET VERIFIED BY RECORDING.

Evok pushes device-change events to a configured webhook URL (evok.py WhHandler):

  * On each status change (devents.status -> status_cb), WhHandler.on_event
    computes device.full() (a list of dev dicts), filters by `device_mask`,
    and if any match:
      - complex_events == False:  GET  <url>  (Content-Type application/json, no body)
      - complex_events == True :  POST <url>  body=json.dumps(filtered list)

To test this we run an in-process HTTP receiver (clients/webhook.py fixture),
but pointing the SERVER's webhook config at it requires editing
/etc/evok/config.yaml and restarting Evok — which we could not do against the
remote test device. Therefore this test is INFERRED from the codebase and is
SKIPPED unless the operator confirms the server's webhook is pointed at the
receiver via EVOK_WEBHOOK_CONFIGURED=1.

This test has NOT been recorded; it is a contract sketch. When a device with
config access is available, run with EVOK_TEST_MODE=record and
EVOK_WEBHOOK_CONFIGURED=1 to capture and verify.
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("EVOK_WEBHOOK_CONFIGURED") != "1",
    reason="webhook test requires the server's webhook.address configured to "
    "the receiver; set EVOK_WEBHOOK_CONFIGURED=1",
)


async def test_webhook_emits_post_on_change(http, webhook_receiver):
    """Trigger a DO change via REST and expect the webhook receiver to get a POST
    (assuming complex_events=true) carrying the changed device in its body."""
    # Change DO 1_01 to the opposite of a known state, then restore.
    before = http.get("/rest/do/1_01/").body.get("value")
    new = 0 if before else 1
    http.post_form("/rest/do/1_01/", {"value": str(new)})

    # Give the server a moment to dispatch the webhook.
    await asyncio.sleep(1.0)
    http.post_form("/rest/do/1_01/", {"value": str(before)})  # restore

    posts = webhook_receiver.capture.posts
    assert posts, (
        "no webhook POST received; is webhook.enabled + complex_events true "
        "and address pointing here?"
    )
    # At least one POST body should mention the changed DO.
    found = any(
        any(
            isinstance(e, dict) and e.get("dev") == "do" and e.get("circuit") == "1_01"
            for e in (p["body"] if isinstance(p["body"], list) else [p["body"]])
        )
        for p in posts
    )
    assert found, f"changed DO 1_01 not present in any webhook payload; posts={posts!r}"


async def test_webhook_emits_get_when_not_complex(http, webhook_receiver):
    """When complex_events=false the server sends an empty GET (no body).

    NOTE: this and the POST case are mutually exclusive on a single server
    config. This test is a contract sketch for the GET variant and will only
    pass if the server is configured with complex_events=false. Treat as
    documentation of the alternate contract until recorded.
    """
    before = http.get("/rest/do/1_01/").body.get("value")
    http.post_form("/rest/do/1_01/", {"value": "0" if before else "1"})
    await asyncio.sleep(1.0)
    http.post_form("/rest/do/1_01/", {"value": str(before)})
    assert webhook_receiver.capture.gets, "no webhook GET received; is complex_events=false?"
