"""Bulk API functional tests (batch group_queries / group_assignments / individual_assignments)."""


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
    # BUG #1 (see FINDINGS.md) is FIXED: group_queries used map() (lazy), which
    # is not JSON-serializable, and returned an error envelope. Now each query
    # returns the list of the states of its devices, in the order of the queries.
    payload = {"group_queries": [{"device_types": ["di"]}, {"device_types": ["ro"]}]}
    r = http.post_json("/bulk/", payload)
    assert r.status == 200, r.raw_text
    body = r.body
    assert "group_queries" in body, body
    assert isinstance(body["group_queries"], list)
    assert len(body["group_queries"]) == 2
