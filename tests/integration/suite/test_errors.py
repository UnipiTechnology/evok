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
    # The range of the schema (`minimum: 0` of ao.value) is checked on both
    # endpoints, also for the strings of a form of /rest/*; a value out of the
    # range is refused before any write. This test uses /json/, the same JSON body
    # to /rest/* is covered by test_error_rest_silently_noops_json_body.
    r = http.post_json("/json/ao/1_01/", {"value": -1})
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_ai_unknown_mode(http):
    # The AI schema allows `mode` as a free string (no enum), so jsonschema
    # passes; the device refuses a mode which is not in its `modes` (ValueError
    # "unknown mode") with 400 before any write.
    r = http.post_json("/rest/ai/1_01/", {"mode": "BogusMode"})
    assert r.status == 400, r.raw_text
    _assert_error_envelope(r.body)


def test_error_invalid_property_underscore(http):
    # The server rejects property reads whose first char is '_'.
    r = http.get("/rest/ro/2_01/_internal")
    assert r.status in (404, 400), r.raw_text
    _assert_error_envelope(r.body)


def test_error_rest_silently_noops_json_body(http):
    # BUG #3 (see FINDINGS.md) is FIXED (the name of the test is kept for its
    # cassette): a JSON body to /rest/* gave an empty kw dict (body_arguments is
    # empty for JSON), set(**{}) changed nothing and returned 200/success. /rest/*
    # now reads a JSON body when there are no form fields, so the params are
    # validated as on /json/ (see test_error_ao_value_below_minimum): -1 is
    # refused with 400.
    r = http.post_json("/rest/ao/1_01/", {"value": -1})
    assert r.status == 400, r.raw_text
    _assert_error_envelope(r.body)


def test_error_property_read_unit(http):
    # BUG #2 (see FINDINGS.md) is FIXED: the property-read path used to do
    # getattr(device, prop) while AI exposed `unit` in full() via `unit_name`,
    # leaking an AttributeError. `unit` is now a real read path and returns the
    # value. This asserts the corrected behavior.
    r = http.get("/rest/ai/1_01/unit")
    assert r.status == 200, r.raw_text
    assert r.body == {"unit": "V"}, r.body
