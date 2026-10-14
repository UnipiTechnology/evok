"""Generate a contract JSON Schema per devtype from the recorded golden cassettes.

The contract schema is the offline CI oracle. Replay mode serves responses from
cassettes; this generator reads those same cassettes once and infers, per
device type, the shape that every response of that type must conform to:

  * required keys (intersection across all observed instances — a key present in
    every observed response is required; a key missing from some is optional)
  * per-key JSON type (bool / int / float / str / array / object), with int/float
    unioned when both appear (e.g. value may be 0 or 0.0)
  * enum membership when a string/number field takes a small set of distinct
    values across observations (e.g. mode: {Simple, PWM})
  * numeric range (min/max) for scalar numeric fields
  * array element type for list fields

The output is written to spec/spec.json. Replay validates every served
response against it (see oracles/contract.py), so a regression that changes a
field type (pending: false -> "false"), drops a required key, or leaves an enum
fails offline CI without hardware.

This is the "extract, don't author" principle applied to the contract: the
schema is inferred from recorded behavior, not hand-maintained. Re-run after
`EVOK_TEST_MODE=record` whenever behavior intentionally changes.

Usage:
    uv run python tools/extract_spec_from_cassettes.py
    uv run python tools/extract_spec_from_cassettes.py --check  # fail if spec.json drifts
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

SPECDIR = Path(__file__).resolve().parent.parent / "spec"
GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"
SPEC = SPECDIR / "spec.json"

# A field is treated as an enum if the number of distinct observed values is at
# most this many AND all values are strings or ints (not floats — floats are
# readings, not categories).
ENUM_MAX_DISTINCT = 8


def jsontype(v):
    """Map a Python value to a JSON Schema type name. bool before int (bool is int in Python)."""
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "null"
    return "string"  # fallback


def merge_type(types: set[str]) -> dict:
    """Build a JSON Schema 'type' fragment from observed Python types."""
    # Drop null — optional nullability handled via required, not type union, to
    # keep the schema strict (a field that was non-null in all samples should
    # not suddenly become null).
    types = {t for t in types if t != "null"}
    if not types:
        return {}
    if len(types) == 1:
        return {"type": next(iter(types))}
    # int + number -> number (number subsumes integer in JSON Schema)
    if types == {"integer", "number"}:
        return {"type": "number"}
    # multiple distinct types -> oneOf (e.g. string|number for value coercion)
    return {"oneOf": [{"type": t} for t in sorted(types)]}


def infer_field(samples: list) -> dict:
    """Infer a JSON Schema fragment for one field from its observed values."""
    types = {jsontype(v) for v in samples}
    schema = merge_type(types)

    # Enum detection: small distinct set of string/integer values (hashable scalars only).
    non_null = [v for v in samples if v is not None]
    hashable_scalars = [
        v for v in non_null if isinstance(v, (str, int)) and not isinstance(v, bool)
    ]
    distinct = set(hashable_scalars)
    scalar_cat = len(hashable_scalars) == len(non_null)
    if scalar_cat and 1 <= len(distinct) <= ENUM_MAX_DISTINCT:
        # Sort by (string form, JSON type) so values with identical string forms
        # (e.g. int 0 vs str "0") are ordered deterministically regardless of
        # set iteration order / hash randomization.
        schema["enum"] = sorted(distinct, key=lambda v: (str(v), jsontype(v)))

    # Numeric range.
    nums = [v for v in non_null if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if nums:
        schema["minimum"] = min(nums)
        schema["maximum"] = max(nums)

    # Array element type.
    arrays = [v for v in non_null if isinstance(v, list)]
    if arrays and all(isinstance(a, list) for a in arrays):
        elems = [e for a in arrays for e in a]
        if elems:
            elem_types = {jsontype(e) for e in elems}
            elem_dicts = [e for e in elems if isinstance(e, dict)]
            if elem_dicts:
                schema["items"] = infer_object(elem_dicts)
            else:
                schema["items"] = merge_type(elem_types)
    # Dict-valued field (e.g. ai/ao 'modes' is a dict of mode->metadata): infer as object.
    dict_vals = [v for v in non_null if isinstance(v, dict)]
    if dict_vals and "type" not in schema:
        schema = infer_object(dict_vals)
    return schema


def infer_object(dicts: list[dict], additional_properties: bool = True) -> dict:
    """Infer an object schema from a list of dict samples.

    additional_properties=False makes the schema strict (only observed keys
    allowed) — used for input/write-param contracts so a non-spec param fails.
    Response schemas stay permissive (True) so a server adding a field doesn't
    break replay.
    """
    # Collect per-key samples and presence counts.
    key_samples: dict[str, list] = defaultdict(list)
    key_present: dict[str, int] = defaultdict(int)
    for d in dicts:
        for k, v in d.items():
            key_samples[k].append(v)
            key_present[k] += 1
    properties = {}
    required = []
    for k, samples in key_samples.items():
        properties[k] = infer_field(samples)
        # required if present in EVERY observed dict
        if key_present[k] == len(dicts):
            required.append(k)
    schema = {
        "type": "object",
        "additionalProperties": additional_properties,
        "properties": properties,
    }
    if required:
        schema["required"] = sorted(required)
    return schema


def extract_device_payloads() -> dict[str, list[dict]]:
    """Walk all HTTP cassettes; return {devtype: [payload dicts]}.

    A payload is the device's own full() dict — extracted from either:
      * a direct read response body (the dict itself, if it has 'dev'), or
      * a write response body's 'result' field, or
      * elements of a list response (e.g. /rest/all) that have 'dev'.
    Error envelopes (success: false) are skipped — they're not device payloads.
    """
    payloads: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text())
        for _rid, entry in data.items():
            if "response" not in entry:
                continue  # WS entry
            body = entry["response"]["body"]
            for d in _device_dicts(body):
                payloads[d["dev"]].append(d)
    return payloads


def extract_input_params() -> dict[str, list[dict]]:
    """Walk all HTTP cassettes; return {devtype: [input body dicts]}.

    Collects the POST request bodies (form-encoded or JSON) keyed by the devtype
    in the path (e.g. /rest/do/1_01/ -> 'do'). These are the observed write
    parameters per device type — the input half of the contract, inferred from
    real requests rather than hand-authored.
    """
    inputs: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(GOLDEN.glob("*.json")):
        data = json.loads(path.read_text())
        for _rid, entry in data.items():
            req = entry.get("request")
            if not req or req.get("kind") != "http" or req.get("method") != "POST":
                continue
            body = req.get("form") or req.get("json")
            if not isinstance(body, dict):
                continue
            # devtype = first path segment after /rest/ or /json/
            parts = [p for p in (req.get("path") or "").split("/") if p]
            if len(parts) < 2 or parts[0] not in ("rest", "json"):
                continue
            dev = parts[1]
            # skip RPC (/rpc) and bulk (/bulk) — handled elsewhere
            inputs[dev].append(body)
    return inputs


def _device_dicts(body) -> list[dict]:
    """Extract device payload dicts from a response body."""
    out = []
    if isinstance(body, dict):
        if body.get("success") is False:
            return out  # error envelope, not a device
        if "dev" in body and "circuit" in body:
            out.append(body)
        if isinstance(body.get("result"), dict) and "dev" in body["result"]:
            out.append(body["result"])
    elif isinstance(body, list):
        for e in body:
            if isinstance(e, dict) and "dev" in e and "circuit" in e:
                out.append(e)
    return out


def generate() -> dict:
    payloads = extract_device_payloads()
    inputs = extract_input_params()
    contract = {
        "$schema": "http://json-schema.org/draft-2020-12/schema",
        "device_types": {},
    }
    all_devs = sorted(set(payloads) | set(inputs))
    for dev in all_devs:
        entry: dict = {}
        if dev in payloads:
            entry["response"] = infer_object(payloads[dev])
        if dev in inputs:
            entry["input"] = infer_object(inputs[dev], additional_properties=False)
        contract["device_types"][dev] = entry
    return contract


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if spec.json would change")
    args = ap.parse_args()

    contract = generate()
    SPECDIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        if not SPEC.exists():
            print("spec.json missing; generate first (run without --check)", file=sys.stderr)
            return 1
        current = json.loads(SPEC.read_text())
        if current != contract:
            print("spec.json is stale; regenerate (run without --check)", file=sys.stderr)
            return 1
        print("spec.json up to date")
        return 0

    SPEC.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    print(f"wrote {SPEC} ({len(contract['device_types'])} device types)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
