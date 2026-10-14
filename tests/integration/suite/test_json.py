"""JSON API functional tests (POST with JSON body, mirrors REST semantics)."""

import pytest
from tests.integration.oracles.shapes import assert_full_shape, assert_value_in_range

pytestmark = pytest.mark.replay


@pytest.mark.parametrize("dev, circuit", [("di", "2_01"), ("ai", "1_01"), ("ro", "2_01")])
def test_json_get(http, park_output, dev, circuit):
    if dev in ("ro", "ao"):
        next(park_output(dev, circuit, 0))
    r = http.get(f"/json/{dev}/{circuit}/")
    assert r.status == 200, r.raw_text
    assert_full_shape(dev, r.body)
    if "value" in r.body:
        assert_value_in_range(dev, r.body["value"])


def test_json_all(http, park_outputs):
    r = http.get("/json/all/")
    assert r.status == 200
    assert isinstance(r.body, list)


def test_json_post(http):
    r = http.post_json("/json/do/1_01/", {"value": 1})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
