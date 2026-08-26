"""Structural assertion oracles derived from the generated contract.

The spec (spec/spec.json) is generated from the golden cassettes by
tools/extract_spec_from_cassettes.py — it is NOT hand-authored. These oracles wrap it
for the test suite: presence/required-key checks for responses and param
membership for inputs. Type/enum/range enforcement happens in oracles/contract.py
(used directly by the replay transport); these helpers add readable assertions
in tests.
"""

from tests.integration.oracles.contract import input_devtypes, response_devtypes


def resolve_devtype(dev: str) -> str | None:
    """Return the canonical devtype name, or None if unknown to the contract.

    The contract keys are the `dev` values actually observed (e.g. 'temp', not
    'sensor'); aliases are not separately registered here because the contract
    is keyed by observed dev field.
    """
    if dev in response_devtypes() or dev in input_devtypes():
        return dev
    return None


def assert_full_shape(dev: str, payload: dict) -> None:
    """Assert a read snapshot has the required keys for its devtype.

    Required-key enforcement is also done by the contract validator (which the
    replay transport runs on every response); this helper is a readable
    in-test assertion that names the missing keys explicitly.
    """
    canon = resolve_devtype(dev)
    assert canon is not None, f"unknown device type {dev!r} (not in contract)"
    keys = set(payload)
    # Re-derive required keys from the contract for the message.
    import json
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).resolve().parent.parent / "spec" / "spec.json").read_text()
    )
    required = contract["device_types"][canon].get("response", {}).get("required", [])
    missing = [k for k in required if k not in payload]
    assert not missing, f"{dev}: full() missing required keys {missing}; got {sorted(keys)}"
    assert payload.get("dev") == dev or payload.get("dev") in (dev,), (
        f"{dev}: 'dev' field {payload.get('dev')!r} inconsistent with type"
    )
    assert "circuit" in payload, f"{dev}: full() missing 'circuit'"


def assert_set_params(dev: str, **params) -> None:
    """Assert a write payload only uses params observed in the contract for `dev`."""
    canon = resolve_devtype(dev)
    assert canon is not None, f"unknown device type {dev!r}"
    import json
    from pathlib import Path

    contract = json.loads(
        (Path(__file__).resolve().parent.parent / "spec" / "spec.json").read_text()
    )
    allowed = set(contract["device_types"][canon].get("input", {}).get("properties", {}).keys())
    unknown = set(params) - allowed
    assert not unknown, f"{dev}: set() got non-contract params {unknown}; allowed {sorted(allowed)}"


def assert_value_in_range(dev: str, value) -> None:
    """Coarse range checks for read values (hardware-dependent, so loose).

    The contract validator enforces numeric ranges strictly; this helper is for
    in-test readability where a value is hardware-dependent and only its
    category (binary/analog) is asserted.
    """
    canon = resolve_devtype(dev)
    if canon is None:
        return
    if canon in ("ro", "do", "led", "di", "wd", "owpower"):
        assert value in (0, 1, True, False), f"{dev}: binary value out of range: {value!r}"
    elif canon in ("ai", "ao", "sensor", "temp", "1wdevice", "data_point"):
        assert value is None or isinstance(value, (int, float)), (
            f"{dev}: expected numeric value, got {value!r}"
        )
