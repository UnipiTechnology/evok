"""The communication of the devices: comm and last_comm, the unit which does not respond.

The mockbus does not serve the unit 3 of the configuration (mockbus/config.py OFFLINE_UNIT).
"""

import pytest
from tests.integration.mockbus.config import OFFLINE_UNIT


def _assert_comm_ok(state: dict) -> None:
    assert state["comm"] == "ok", state
    assert isinstance(state["last_comm"], (int, float)), state
    assert 0 <= state["last_comm"] < 10, state


@pytest.mark.parametrize(
    "dev, circuit", [("do", "1_01"), ("di", "2_01"), ("ai", "1_01"), ("wd", "1")]
)
def test_comm_of_modbus_device(http, dev, circuit):
    _assert_comm_ok(http.get(f"/rest/{dev}/{circuit}/").body)


def test_comm_of_1wire_sensor(http):
    sensors = [s for s in http.get("/rest/sensor/all/").body if s["dev"] == "temp"]
    assert sensors
    _assert_comm_ok(sensors[0])


def test_comm_of_modbus_unit(http):
    state = http.get("/rest/modbus_slave/1/").body
    _assert_comm_ok(state)
    assert state["scan_error"] is None


def test_unit_which_does_not_respond(http):
    r = http.get(f"/rest/modbus_slave/{OFFLINE_UNIT}/")
    if r.status == 404:
        pytest.skip("the server has no unit which does not respond")
    state = r.body
    assert state["comm"] in ("timeout", "error"), state
    assert isinstance(state["scan_error"], str) and state["scan_error"], state
    assert state["last_comm"] is None, state


def test_other_units_beside_the_unit_which_does_not_respond(http):
    """A unit which does not respond does not stop the others on the bus"""
    for unit in ("1", "2"):
        _assert_comm_ok(http.get(f"/rest/modbus_slave/{unit}/").body)
