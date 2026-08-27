"""JSON-RPC 2.0 functional tests against /rpc."""

import pytest

pytestmark = pytest.mark.replay


def test_rpc_input_get(rpc):
    # returns [value, debounce] per Evok RPC contract
    result = rpc.call("input_get", ["2_01"])
    assert isinstance(result, list) and len(result) == 2


def test_rpc_relay_get(rpc):
    result = rpc.call("relay_get", ["2_01"])
    # On this firmware relay_get returns the bare state value (0/1),
    # not a [value, pending] tuple.
    assert result in (0, 1, True, False)


def test_rpc_output_set(rpc):
    result = rpc.call("output_set", ["1_01", "1"])
    assert result in (0, 1, True, False)


def test_rpc_unknown_method(rpc):
    # MethodNotFound must be surfaced as an error, not a crash.
    with pytest.raises(AssertionError):
        rpc.call("nonexistent_method_xyz", ["2_01"])
