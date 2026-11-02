"""Readable assertions on the device states, by the definition of the API (oracles.contract).

The contract validator checks every state of every response (clients.http); these
helpers name the missing keys or the wrong category of a value in the test.
"""

from tests.integration.oracles.contract import device_types, state_schema


def resolve_devtype(dev: str) -> str | None:
    """The device type if the definition of the API knows it, else None"""
    return dev if dev in device_types() else None


def assert_full_shape(dev: str, payload: dict) -> None:
    """The state has the required keys of its device type"""
    schema = state_schema(dev)
    assert schema is not None, f"unknown device type {dev!r} (not in the definition of the API)"
    missing = [k for k in schema.get("required", []) if k not in payload]
    assert not missing, f"{dev}: full() missing required keys {missing}; got {sorted(payload)}"
    assert payload.get("dev") == dev, (
        f"{dev}: 'dev' field {payload.get('dev')!r} inconsistent with type"
    )


def assert_value_in_range(dev: str, value) -> None:
    """The category of a value which depends on the hardware: binary or analog"""
    if dev in ("ro", "do", "led", "di", "wd", "owpower", "nv_save"):
        assert value in (0, 1, None), f"{dev}: binary value out of range: {value!r}"
    elif dev in ("ai", "ao", "temp", "data_point"):
        # a value which is not a number is the string 'NaN', 'Infinity' or '-Infinity'
        assert (
            value is None
            or value in ("NaN", "Infinity", "-Infinity")
            or (isinstance(value, (int, float)) and not isinstance(value, bool))
        ), f"{dev}: expected numeric value, got {value!r}"
