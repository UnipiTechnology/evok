"""The tokens of the APIs: 401 without a token, the read_token only reads.

Skipped when the server does not require a token (the mockbus does, see
mockbus/config.py). See docs/security.md.
"""

import pytest
import websockets

pytestmark = pytest.mark.usefixtures("tokens_required")

UNAUTHORIZED = {"success": False, "errors": {"Unauthorized": "Missing or invalid token"}}


def test_without_token_is_401(http_as):
    r = http_as(None).get("/rest/do/1_01/")
    assert r.status == 401, r.raw_text
    assert r.body == UNAUTHORIZED
    assert "Bearer" in r.headers.get("www-authenticate", ""), r.headers


def test_wrong_token_is_401(http_as):
    r = http_as("not-the-token").get("/rest/do/1_01/")
    assert r.status == 401, r.raw_text
    assert r.body == UNAUTHORIZED


def test_version_without_token(http_as):
    r = http_as(None).get("/version")
    assert r.status == 200, r.raw_text
    assert r.body.startswith("v")


def test_read_token_reads(http_as, read_token):
    r = http_as(read_token).get("/rest/do/1_01/")
    assert r.status == 200, r.raw_text
    assert r.body["dev"] == "do"


def test_read_token_cannot_change(http_as, read_token):
    r = http_as(read_token).post_form("/rest/do/1_01/", {"value": "0"})
    assert r.status == 403, r.raw_text
    assert r.body["success"] is False
    assert "ReadOnlyAccess" in r.body["errors"]


def test_read_token_bulk(http_as, read_token):
    client = http_as(read_token)
    r = client.post_json("/bulk/", {"group_queries": [{"device_types": ["do"]}]})
    assert r.status == 200, r.raw_text
    # a request with an assignment is refused as a whole, also its queries
    r = client.post_json(
        "/bulk/",
        {
            "group_queries": [{"device_types": ["do"]}],
            "individual_assignments": [
                {"device_type": "do", "device_circuit": "1_01", "assigned_values": {"value": 0}}
            ],
        },
    )
    assert r.status == 403, r.raw_text
    assert "ReadOnlyAccess" in r.body["errors"]


def test_read_token_rpc(http_as, read_token):
    from tests.integration.clients.rpc import RpcClient

    rpc = RpcClient(http_as(read_token))
    assert rpc.call("output_get", ["1_01"])[0] in (0, 1)
    reply = rpc.call_raw("output_set", ["1_01", 0])
    assert reply["error"]["code"] == -32001, reply


async def test_read_token_websocket_set_is_refused(ws_as, read_token):
    msgs = (
        await ws_as(read_token)
        .will_send({"cmd": "set", "dev": "do", "circuit": "1_01", "value": 0})
        .run(receive_for=1.0)
    )
    errors = [m for m in msgs if isinstance(m, dict) and m.get("success") is False]
    assert errors, msgs
    assert "ReadOnlyAccess" in errors[0]["errors"]


async def test_websocket_without_token_is_refused(ws_as):
    with pytest.raises(websockets.InvalidStatus) as error:
        await ws_as(None).will_send({"cmd": "all"}).run(receive_for=0.5)
    assert error.value.response.status_code == 401
