"""1-Wire sensor (DS18B20) tests — recorded against a live Neuron M103.

The sensor registers with circuit = 1-Wire address with dots stripped
(e.g. "28.CD79A9080000.4A" -> "28CD79A90800004A"), and reports ``dev: "temp"``
(not ``"sensor"``) in its full() payload, with fields:
  dev, circuit, address, value (°C), lost, time, interval, type.

Covers:
  * read via /rest/sensor/<circuit>/ and via /rest/all/
  * RPC sensor_get / sensor_get_value
  * set interval (configuration write; safe)
  * owbus_list RPC returns the discovered address under the DS18B20 key

NOTE: the circuit is device-specific (tied to this physical sensor). If the
sensor is swapped, re-record these cassettes.
"""

import pytest

pytestmark = pytest.mark.replay

# Tied to the physical DS18B20 currently on the test rig's 1-Wire bus.
SENSOR_CIRCUIT = "28CD79A90800004A"
SENSOR_ADDRESS = "28.CD79A9080000.4A"
SENSOR_TYPE = "DS18B20"


def test_sensor_in_all(http):
    r = http.get("/rest/all/")
    assert r.status == 200
    sensors = [e for e in r.body if isinstance(e, dict) and e.get("dev") == "temp"]
    assert sensors, "no 'temp' device in /rest/all (is the 1-Wire sensor connected?)"
    s = next((e for e in sensors if e.get("circuit") == SENSOR_CIRCUIT), None)
    assert s is not None, (
        f"sensor {SENSOR_CIRCUIT} not found; got {[e['circuit'] for e in sensors]}"
    )
    assert s["type"] == SENSOR_TYPE
    assert s["address"] == SENSOR_ADDRESS
    assert "value" in s and "lost" in s and "interval" in s


def test_sensor_get_full(http):
    r = http.get(f"/rest/sensor/{SENSOR_CIRCUIT}/")
    assert r.status == 200, r.raw_text
    s = r.body
    assert s["dev"] == "temp"
    assert s["circuit"] == SENSOR_CIRCUIT
    assert s["address"] == SENSOR_ADDRESS
    assert s["type"] == SENSOR_TYPE
    assert isinstance(s["value"], (int, float))
    assert s["lost"] in (True, False)
    assert isinstance(s["interval"], (int, float))


def test_rpc_sensor_get(rpc):
    # sensor_get returns (value, lost, readtime, interval)
    result = rpc.call("sensor_get", [SENSOR_CIRCUIT])
    assert isinstance(result, list) and len(result) == 4
    assert isinstance(result[0], (int, float))  # value
    assert isinstance(result[1], bool)  # lost


def test_rpc_sensor_get_value(rpc):
    result = rpc.call("sensor_get_value", [SENSOR_CIRCUIT])
    assert isinstance(result, (int, float))


def test_rpc_owbus_list_sees_sensor(rpc):
    result = rpc.call("owbus_list", ["OWBUS"])
    assert isinstance(result, dict)
    assert SENSOR_TYPE in result
    assert SENSOR_ADDRESS in result[SENSOR_TYPE], f"{SENSOR_ADDRESS} not in {result}"


def test_sensor_set_interval(http):
    # interval is a safe configuration write. Read current, set 15, restore.
    before = http.get(f"/rest/sensor/{SENSOR_CIRCUIT}/").body.get("interval")
    r = http.post_json(f"/rest/sensor/{SENSOR_CIRCUIT}/", {"interval": 15})
    assert r.status == 200, r.raw_text
    assert r.body.get("success") is True
    # restore
    if before is not None:
        http.post_json(f"/rest/sensor/{SENSOR_CIRCUIT}/", {"interval": before})
