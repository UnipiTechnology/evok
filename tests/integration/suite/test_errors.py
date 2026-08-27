"""Error & validation contract tests.

Pins the error envelope shape and status codes the server returns for bad
input. The security review noted the server returns HTTP 404 for server-side
errors (a misuse) and leaks exception class names + messages. These tests
encode the CURRENT behavior so replay passes; if the error contract is
intentionally improved (correct statuses, sanitized messages), re-record.

Observed envelope (handlers_base.py / evok.py): on exception the handler writes
  {"success": false, "errors": {<ExceptionClassName>: <str>}}
and sets status 404.
"""

import pytest

pytestmark = pytest.mark.replay


def _assert_error_envelope(body) -> None:
    assert isinstance(body, dict), f"expected error dict, got {type(body).__name__}: {body!r}"
    assert body.get("success") is False, f"expected success=false, got {body!r}"
    assert "errors" in body and isinstance(body["errors"], dict), f"missing errors dict: {body!r}"


def test_error_unknown_device_type(http):
    r = http.get("/rest/nosuchdev/1/")
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_unknown_circuit(http):
    r = http.get("/rest/ro/999/")
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_ao_value_below_minimum(http):
    # BUG #3 (see FINDINGS.md): schema validation (jsonschema `minimum: 0`) fires
    # ONLY on the JSON endpoint (/json/*), where the body is parsed as real JSON
    # types. The form-encoded /rest/* endpoint receives values as strings, which
    # bypass `minimum`, so this test deliberately uses /json/ to exercise the
    # validation contract. (Posting JSON to /rest/* silently no-ops instead —
    # see test_error_rest_silently_noops_json_body.)
    r = http.post_json("/json/ao/1_01/", {"value": -1})
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_ai_unknown_mode(http):
    # AI schema allows `mode` as a free string (no enum), so jsonschema passes;
    # the device's set() silently ignores a mode not in self.modes. Record the
    # ACTUAL behavior (likely success:true with no mode change) rather than
    # assuming a rejection.
    r = http.post_json("/rest/ai/1_01/", {"mode": "BogusMode"})
    assert r.status == 200, r.raw_text
    # restore real mode
    http.post_json("/rest/ai/1_01/", {"mode": "Voltage"})
    # Assert the observed contract: unknown mode is silently accepted/ignored.
    assert isinstance(r.body, dict)
    assert r.body.get("success") is True, (
        f"expected silent-accept of unknown AI mode (current behavior); got {r.body!r}"
    )


def test_error_invalid_property_underscore(http):
    # The server rejects property reads whose first char is '_'.
    r = http.get("/rest/ro/2_01/_internal")
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_rest_silently_noops_json_body(http):
    # BUG #3 (see FINDINGS.md): POSTing a JSON body to the form-encoded /rest/*
    # endpoint yields an empty kw dict (body_arguments is empty for JSON), so
    # set(**{}) runs with no args and the device is unchanged -> 200/success with
    # the current state. Compare against /json/ which actually validates (see
    # test_error_ao_value_below_minimum). This pins the silent-no-op behavior.
    r = http.post_json("/rest/ao/1_01/", {"value": -1})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True, f"expected silent success (current bug); got {r.body!r}"


def test_error_property_not_a_python_attribute(http):
    # BUG #2 (see FINDINGS.md): the property-read path does getattr(device, prop),
    # but some full() keys are NOT Python attributes (e.g. AI exposes `unit` in
    # full() via the `unit_name` property, not `unit`). Reading such a key leaks an
    # AttributeError in the error envelope. This pins the current behavior.
    r = http.get("/rest/ai/1_01/unit")
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)
    # The leaked exception class is part of the (current) contract.
    assert "AttributeError" in r.body["errors"], r.body
