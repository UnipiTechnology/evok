"""Spec validator: validate response/input payloads against spec/spec.json.

Used by replay mode (the offline CI gate). Every response served from a cassette
is validated against the response schema for its devtype; every write request
body is validated against the input schema. A regression that changes a field
type, drops a required key, leaves an enum, or sends a non-spec write param
fails here — offline, deterministic, no hardware.

spec.json is GENERATED from the golden cassettes by
tools/extract_spec_from_cassettes.py (covers both responses and inputs). The hand-
authored spec/data.yaml has been removed; this is the single source of truth.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

SPEC_PATH = Path(__file__).resolve().parent.parent / "spec" / "spec.json"
_contract: dict | None = None
_resp_validators: dict[str, Draft202012Validator] | None = None
_input_validators: dict[str, Draft202012Validator] | None = None


def _load() -> tuple[dict, dict[str, Draft202012Validator], dict[str, Draft202012Validator]]:
    global _contract, _resp_validators, _input_validators
    if _contract is None:
        _contract = json.loads(SPEC_PATH.read_text())
        dt = _contract["device_types"]
        _resp_validators = {
            dev: Draft202012Validator(entry["response"])
            for dev, entry in dt.items()
            if "response" in entry
        }
        _input_validators = {
            dev: Draft202012Validator(entry["input"])
            for dev, entry in dt.items()
            if "input" in entry
        }
    return _contract, _resp_validators, _input_validators


def validate_response(payload: dict) -> list[str]:
    """Validate a device response payload against the response contract."""
    if not isinstance(payload, dict) or "dev" not in payload:
        return []
    _contract, resp_v, _input_v = _load()
    dev = payload["dev"]
    if dev not in resp_v:
        return []
    return sorted(e.message for e in resp_v[dev].iter_errors(payload))


def validate_input(dev: str, body: dict) -> list[str]:
    """Validate a write request body against the input contract for `dev`."""
    _contract, _resp_v, input_v = _load()
    if dev not in input_v:
        return []
    return sorted(e.message for e in input_v[dev].iter_errors(body))


def response_devtypes() -> set[str]:
    _contract, resp_v, _input_v = _load()
    return set(resp_v)


def input_devtypes() -> set[str]:
    _contract, _resp_v, input_v = _load()
    return set(input_v)
