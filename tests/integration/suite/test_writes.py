"""Write/property-read coverage across device types.

Recorded against a Neuron M103 (Evok v3.0.6). The device is standalone (nothing
connected), so writes are safe. Each test leaves the device in a safe/restored
state where the property is configuration-shaped (mode/interval), since
test-run order in `live` mode could otherwise leave stale output state.

Devices NOT present on this board (register, data_point, sensor) are skipped
here; sensor (1-Wire) coverage is pending an OW sensor. See fixtures/devices.yaml.
"""

import pytest
from tests.integration.oracles.shapes import assert_full_shape

pytestmark = pytest.mark.replay


# --- property-read path: GET /rest/<dev>/<circuit>/<prop> ----------------------
# Distinct from full(): returns a single-key dict {prop: value}, and the server
# guards against underscore-prefixed properties (see test_rest_property_read).


@pytest.mark.parametrize(
    "dev, circuit, prop",
    [
        ("di", "2_01", "value"),
        ("ro", "2_01", "value"),
        ("do", "1_01", "mode"),
        ("ai", "1_01", "value"),
        ("ai", "1_01", "mode"),
    ],
)
def test_rest_read_property(http, dev, circuit, prop):
    r = http.get(f"/rest/{dev}/{circuit}/{prop}")
    assert r.status == 200, r.raw_text
    assert isinstance(r.body, dict)
    assert prop in r.body, f"expected {{{prop!r}: ...}}, got {r.body!r}"


# --- AO: value + mode switching (restore to Voltage/0 at end) -----------------


def test_write_ao_value(http):
    r = http.post_json("/rest/ao/1_01/", {"value": 5})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    assert_full_shape("ao", r.body["result"])


def test_write_ao_mode_switch_and_restore(http):
    # Switch to Current, then back to Voltage (safe default). Nothing connected,
    # so mode switching is harmless. We assert success, not the cached value
    # (the scan cache lags the write; see test_boundaries.py for why).
    for mode in ("Current", "Voltage"):
        r = http.post_json("/rest/ao/1_01/", {"mode": mode})
        assert r.status == 200, r.raw_text
        assert r.body.get("success") is True
    # restore a safe value
    http.post_json("/rest/ao/1_01/", {"value": 0})


# --- AI: mode switching (input; safe) -----------------------------------------


def test_write_ai_mode_switch_and_restore(http):
    for mode in ("Current", "Voltage"):
        r = http.post_json("/rest/ai/1_01/", {"mode": mode})
        assert r.status == 200, r.raw_text
        assert r.body.get("success") is True


# --- DI: debounce / counter_mode (safe config writes) -----------------------


def test_write_di_debounce(http):
    r = http.post_json("/rest/di/2_01/", {"debounce": 50})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    assert_full_shape("di", r.body["result"])


def test_write_di_counter_mode_toggle(http):
    # Toggle counter_mode and restore to Enabled.
    r = http.post_json("/rest/di/2_01/", {"counter_mode": "Disabled"})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    http.post_json("/rest/di/2_01/", {"counter_mode": "Enabled"})


# --- Watchdog: timeout + value=0 only. ---------------------------------------
# NOTE: wd `reset` and `nv_save` trigger a board reset / nvsave which would drop
# the Modbus connection mid-session; deliberately NOT exercised here.


def test_write_wd_timeout(http):
    r = http.post_json("/rest/wd/2_01/", {"timeout": 5000})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    assert_full_shape("wd", r.body["result"])


def test_write_wd_value_off(http):
    r = http.post_json("/rest/wd/2_01/", {"value": 0})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True


# --- OwBus: scan_interval / interval (config writes) -------------------------


def test_write_owbus_intervals(http):
    r = http.post_json("/rest/owbus/OWBUS/", {"scan_interval": 60, "interval": 10})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True


# --- OwPower: toggle + restore -----------------------------------------------


def test_write_owpower_toggle(http):
    r = http.post_json("/rest/owpower/1/", {"value": 1})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    # restore to off
    http.post_json("/rest/owpower/1/", {"value": 0})
