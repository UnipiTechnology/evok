"""REST API functional tests.

Black-box: exercises /rest/* over HTTP. Shape assertions from the spec; exact
values hardware-dependent so we assert ranges/membership, not literals.

In replay mode every response comes from a cassette; to (re)generate cassettes
run with EVOK_TEST_MODE=record against a server (real or mock-backed).
"""

import pytest
from tests.integration.oracles.shapes import (
    assert_full_shape,
    assert_value_in_range,
    resolve_devtype,
)

pytestmark = pytest.mark.replay


def test_version(http):
    r = http.get("/version")
    assert r.status == 200
    # version is a plain string body
    assert isinstance(r.body, str) and r.body.startswith("v")


@pytest.mark.parametrize(
    "dev, circuit",
    [
        ("di", "2_01"),
        ("ro", "2_01"),
        ("do", "1_01"),
        ("ai", "1_01"),
        ("ao", "1_01"),
    ],
)
def test_get_device_full(http, park_output, dev, circuit):
    # Park writable outputs in a known state so the read `value` is stable
    # across record/compare runs (inputs are volatile anyway).
    if dev in ("ro", "do", "ao"):
        next(park_output(dev, circuit, 0))
    r = http.get(f"/rest/{dev}/{circuit}/")
    assert r.status == 200, f"{dev}/{circuit}: {r.raw_text}"
    assert_full_shape(dev, r.body)
    if "value" in r.body:
        assert_value_in_range(dev, r.body["value"])


def test_get_all_devices(http, park_outputs):
    r = http.get("/rest/all/")
    assert r.status == 200
    assert isinstance(r.body, list)
    # every element must carry a known dev + circuit
    for entry in r.body:
        assert "dev" in entry and "circuit" in entry
        assert resolve_devtype(entry["dev"]) is not None, f"unknown dev {entry['dev']!r}"


def test_rest_property_read_guarded(http):
    """Reading a property must not expose underscore-prefixed/internal attrs.

    The current server rejects prop[0] in ('_',). Confirm the contract holds.
    """
    r = http.get("/rest/ro/2_01/_internal")
    # server returns 404 + error envelope for invalid property
    assert r.status in (404, 400), r.raw_text
    assert isinstance(r.body, dict)
    assert r.body.get("success") is False or "errors" in r.body


@pytest.mark.parametrize(
    "dev, circuit, value",
    [
        ("ro", "2_01", 1),
        ("do", "1_01", 0),
        ("led", "1_01", 1),
    ],
)
def test_post_device_set(http, dev, circuit, value):
    r = http.post_form(f"/rest/{dev}/{circuit}/", {"value": str(value)})
    assert r.status == 200, f"{dev}/{circuit}: {r.raw_text}"
    assert isinstance(r.body, dict)
    assert r.body.get("success") is True, r.body
    result = r.body.get("result")
    assert isinstance(result, dict)
    assert_full_shape(dev, result)
