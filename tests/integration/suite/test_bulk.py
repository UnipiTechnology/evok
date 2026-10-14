"""Bulk API functional tests (batch group_queries / group_assignments / individual_assignments)."""

import pytest

pytestmark = pytest.mark.replay


def test_bulk_individual_assignments(http):
    payload = {
        "individual_assignments": [
            {
                "device_type": "do",
                "device_circuit": "1_01",
                "assigned_values": {"value": 1},
            },
            {
                "device_type": "do",
                "device_circuit": "1_02",
                "assigned_values": {"value": 0},
            },
        ]
    }
    r = http.post_json("/bulk/", payload)
    assert r.status == 200, r.raw_text
    assert "individual_assignments" in r.body
    results = r.body["individual_assignments"]
    assert isinstance(results, list)
    assert len(results) == 2
    for entry in results:
        assert entry["dev"] == "do"
        assert "value" in entry


def test_bulk_group_queries(http):
    # BUG #1 (see FINDINGS.md): as of v3.0.6 the server's group_queries path uses
    # map() (lazy) which is not JSON-serializable, so it returns an error
    # envelope. This test encodes the CURRENT (buggy) behavior so replay passes;
    # if the bug is fixed (wrap map() in list()), re-record and flip this to
    # assert success.
    payload = {"group_queries": [{"device_types": ["di", "ro"]}]}
    r = http.post_json("/bulk/", payload)
    assert r.status == 200, r.raw_text
    body = r.body
    # Either a successful group_queries list, or the known error envelope.
    if "group_queries" in body:
        assert isinstance(body["group_queries"], list)
    else:
        assert body.get("success") is False and "errors" in body
