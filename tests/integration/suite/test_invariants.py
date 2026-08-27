"""Cross-protocol consistency invariants.

The same device at (approximately) the same instant must report the same state
through REST, JSON, and RPC. These tests catch regressions where one transport
drifts from another — the class of bug a single-protocol test misses.

Runs in live/record against a real or mock-backed server. In replay mode it
asserts against the recorded cassette for each leg.
"""

import pytest

pytestmark = pytest.mark.replay


def test_rest_json_rpc_agree_on_do_value(http, rpc):
    circuit = "1_01"
    # set a known value via RPC, then read via REST and JSON — all must agree.
    rpc.call("output_set", [circuit, "1"])
    rest_val = http.get(f"/rest/do/{circuit}/").body.get("value")
    json_val = http.get(f"/json/do/{circuit}/").body.get("value")
    assert rest_val == json_val, f"REST={rest_val!r} != JSON={json_val!r}"
    # RPC get_state returns [value, pending]; value should match
    rpc_state = rpc.call("output_get", [circuit])
    assert isinstance(rpc_state, list)
    assert rpc_state[0] == rest_val, f"RPC={rpc_state[0]!r} != REST={rest_val!r}"


async def test_rest_and_ws_agree_on_di_value(http, ws, park_outputs):
    circuit = "2_01"
    rest_val = http.get(f"/rest/di/{circuit}/").body.get("value")
    # WS 'all' must contain the same value for this circuit
    msgs = await ws.will_send({"cmd": "all"}).run(receive_for=1.0)
    matched = False
    # WS 'all' yields one message that is itself the list of device snapshots.
    entries = msgs[0] if msgs and isinstance(msgs[0], list) else msgs
    for entry in entries:
        if isinstance(entry, dict) and entry.get("dev") == "di" and entry.get("circuit") == circuit:
            assert entry.get("value") == rest_val, f"WS={entry.get('value')!r} != REST={rest_val!r}"
            matched = True
    assert matched, f"di {circuit} not present in WS 'all' snapshot"
