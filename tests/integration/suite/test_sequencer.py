"""The sequencer of an output: a pulse, a sequence, cancel, and the refused change (409).

The sequencer of DO 1_02 (circuit do_1_02); see docs/apis/sequencer.md.
"""

import time

import pytest

SEQUENCER = "/rest/sequencer/do_1_02/"
OUTPUT = "/rest/do/1_02/"


def _wait_stopped(http, timeout: float = 5.0) -> dict:
    """The state of the sequencer after its sequence ends"""
    end = time.monotonic() + timeout
    while True:
        state = http.get(SEQUENCER).body
        if not state["running"] or time.monotonic() > end:
            return state
        time.sleep(0.1)


@pytest.fixture(autouse=True)
def stopped(http):
    """No sequence runs and the output is 0 before and after each test"""
    http.post_form(SEQUENCER, {"cancel": "1"})
    http.post_form(OUTPUT, {"value": "0"})
    yield
    http.post_form(SEQUENCER, {"cancel": "1"})
    http.post_form(OUTPUT, {"value": "0"})


def test_state_of_sequencer(http):
    r = http.get(SEQUENCER)
    assert r.status == 200, r.raw_text
    assert r.body["output"] == {"dev": "do", "circuit": "1_02"}
    assert r.body["running"] is False
    assert r.body["name"] is None and r.body["step"] is None and r.body["steps"] is None


def test_pulse(http):
    r = http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "0.5"})
    assert r.status == 200, r.raw_text
    assert r.body["result"]["running"] is True
    assert r.body["result"]["name"] == "pulse"
    assert http.get(OUTPUT).body["value"] == 1
    assert _wait_stopped(http)["running"] is False
    assert http.get(OUTPUT).body["value"] == 0


def test_sequence_of_steps(http):
    steps = [{"value": 1}, {"delay": 0.3, "value": 0}, {"delay": 0.3, "value": 1}]
    r = http.post_json(SEQUENCER, {"steps": steps, "final": {"value": 0}})
    assert r.status == 200, r.raw_text
    assert r.body["result"]["running"] is True
    assert r.body["result"]["steps"] == 3
    assert _wait_stopped(http)["running"] is False
    # the last step, final is written only when the sequence is ended by the shutdown
    assert http.get(OUTPUT).body["value"] == 1


def test_change_of_output_while_pulse_runs_is_409(http):
    http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "5"})
    r = http.post_form(OUTPUT, {"value": "0"})
    assert r.status == 409, r.raw_text
    assert r.body["success"] is False
    assert "SequenceRunning" in r.body["errors"]
    assert http.get(OUTPUT).body["value"] == 1


def test_alias_of_output_while_pulse_runs(http):
    """Only the alias of the output can be changed while its sequence runs"""
    http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "5"})
    r = http.post_form(OUTPUT, {"alias": "it_seq_output"})
    assert r.status == 200, r.raw_text
    assert r.body["result"]["alias"] == "it_seq_output"
    http.post_form(OUTPUT, {"alias": ""})


def test_cancel_allows_the_change(http):
    http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "5"})
    r = http.post_form(SEQUENCER, {"cancel": "1"})
    assert r.status == 200, r.raw_text
    assert r.body["result"]["running"] is False
    r = http.post_form(OUTPUT, {"value": "0"})
    assert r.status == 200, r.raw_text


def test_rpc_change_while_pulse_runs(http, rpc):
    http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "5"})
    reply = rpc.call_raw("output_set", ["1_02", 0])
    assert reply["error"]["code"] == -32002, reply


def test_rpc_pulse_by_the_sequencer(http, rpc):
    rpc.call("output_set_for_time", ["1_02", 1, 0.5])
    assert http.get(SEQUENCER).body["running"] is True
    assert _wait_stopped(http)["running"] is False
    assert http.get(OUTPUT).body["value"] == 0


async def test_websocket_set_while_pulse_runs(http, ws):
    http.post_form(SEQUENCER, {"value": "1", "pulse_duration": "5"})
    msgs = await ws.will_send({"cmd": "set", "dev": "do", "circuit": "1_02", "value": 0}).run(
        receive_for=1.0
    )
    errors = [m for m in msgs if isinstance(m, dict) and m.get("success") is False]
    assert errors, msgs
    assert "SequenceRunning" in errors[0]["errors"]


@pytest.mark.parametrize(
    "params",
    [
        {"value": 1, "pulse_duration": 1, "cancel": True},  # more requests at once
        {"value": 1},  # value without pulse_duration
        {"value": 1, "pulse_duration": 0},  # pulse_duration must be > 0
        {"steps": [{"delay": -1, "value": 1}]},  # a negative delay
        {"final": {"value": 0}},  # final without steps
    ],
)
def test_invalid_request_is_400(http, params):
    r = http.post_json(SEQUENCER, params)
    assert r.status == 400, r.raw_text
    assert http.get(SEQUENCER).body["running"] is False
