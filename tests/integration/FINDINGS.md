# Evok — known bugs found by the integration harness

Bugs discovered while recording the black-box integration suite against Evok
v3.0.6 on a Neuron M103. Each is pinned by a test in `tests/integration/suite/`
that encodes the CURRENT (buggy) behavior so the harness passes; the tests
document the bug inline and will need re-recording once fixed.

Status legend:
  - [pinned]    harness records the buggy behavior; fix → re-record the cassette
  - [quirk]     arguably intended/by-design, but surprising; documented

---

## 1. Bulk `group_queries` / `group_assignments` crash on JSON serialization

**Severity:** functional bug (the endpoint is broken for its primary use case)
**Location:** `evok/evok.py:329, 331, 355, 357` (`JSONBulkHandler.post`)
**Pinned by:** `tests/integration/suite/test_bulk.py::test_bulk_group_queries`

The handler builds the response with `map(methodcaller('full'), all_devs)`
(lazy iterator) instead of `list(map(...))`. When `json.dumps(result)` runs, the
`map` object is not JSON-serializable, so the whole request fails with:

```json
{"success": false, "errors": {"TypeError": "Object of type map is not JSON serializable"}}
```

Both `group_queries` and `group_assignments` are affected (4 call sites). The
`individual_assignments` path uses a list and works.

**Fix:** wrap each `map(...)` in `list(...)`:
```python
result["group_queries"] = [list(map(methodcaller("full"), all_devs))]
```

---

## 2. REST property-read leaks `AttributeError` for non-attribute `full()` keys

**Severity:** minor (information leak + inconsistency)
**Location:** `evok/handlers_base.py:34` (`getattr(device, prop)` in `EvokWebHandlerBase.get`)
**Pinned by:** `tests/integration/suite/test_errors.py::test_error_property_not_a_python_attribute`

`GET /rest/<dev>/<circuit>/<prop>` does `getattr(device, prop)`, but some keys
present in `device.full()` are NOT Python attributes. Example: `AnalogInput`
exposes `unit` in `full()` (via the `unit_name` property), but the attribute is
named `unit_name`, not `unit`. Reading `/rest/ai/1_01/unit` returns a 404 with
the raw `AttributeError` class name and message in the body:

```json
{"success": false, "errors": {"AttributeError": "'AnalogInput' object has no attribute 'unit'"}}
```

The property-read path is therefore inconsistent with `full()`: a client can't
read every key that `full()` advertises. The only guard is `prop[0] in ('_',)`
(handlers_base.py:31), which blocks underscore-prefixed names but not
attribute/key mismatches.

**Fix options:**
  - (a) make property-read consult a whitelist derived from `full()` keys, or
  - (b) rename `unit_name` → `unit` (and audit other `*_name` attrs), or
  - (c) return a structured "no such property" error without leaking the
    exception class.

---

## 3. REST (`/rest/*`) silently no-ops JSON POST bodies

**Severity:** moderate (silent data loss; validation bypass)
**Location:** `evok/handlers_base.py` (`LegacyRestHandler._get_kw`) + `evok/evok.py`
**Pinned by:** `tests/integration/suite/test_errors.py::test_error_ao_value_below_minimum`

`LegacyRestHandler._get_kw` reads `self.request.body_arguments` (form-encoded
key/value pairs). A client POSTing a JSON body (`Content-Type: application/json`,
body `{"value": -1}`) gets an **empty dict** because there are no form fields,
so `device.set(**{})` runs with no arguments and the device is unchanged —
returning 200/success with the *current* state. Schema validation
(`jsonschema.validate`) never fires because `kw` is empty, so the `minimum: 0`
constraint on `ao.value` is bypassed on the REST endpoint.

The JSON endpoint (`/json/*`, `LegacyJsonHandler._get_kw` = `json.loads(body)`)
parses real JSON types and DOES enforce the schema: `POST /json/ao/1_01/ {"value":-1}`
correctly returns 404 `ValidationError`.

So the same write behaves differently on `/rest/*` vs `/json/*`: one silently
no-ops, the other validates. A client using `/rest/*` with JSON bodies gets
silent failures and no validation.

**Fix:** in `LegacyRestHandler._get_kw`, fall back to `json.loads(self.request.body)`
when `body_arguments` is empty and the body is non-empty JSON (as `LegacyJsonHandler`
already does). Or document that `/rest/*` is form-encoded only and reject JSON
bodies with a 415.

---

## 4. `value` is scan-cache-lagged in write responses (not a crash, but a contract gap)

**Severity:** design quirk (not strictly a bug, but a footgun)
**Location:** `evok/modbus_slave.py` — every device `set()` returns `self.full()`
**Pinned by:** `tests/integration/suite/test_boundaries.py` (skipped, with full explanation)

`set()` writes to the bus then returns `self.full()`, whose `value` reflects the
LAST scan cache, not the just-written value. The quantize/clamp returns from
`set_value()` (e.g. AO clamps to `[0, 4095]`, WD timeout→65535) are discarded by
`set()` (it returns `full()`, not the write result). The updated cache appears
only after the next scan (~20ms), which races the request/response.

Consequence: the response `value` of a write is non-deterministic relative to
the request, and the documented clamps (AO 0–10V, register 65535, counter wrap)
are NOT observable through the HTTP API in a single round-trip. The harness
treats `value` as volatile everywhere in compare mode for this reason (see
`cassette.py`).

**Not a fix request** — documenting it because it shaped the harness design
(why `value` can't be exact-compared). If the API ever echoes the clamped
write value or adds a read-after-stable endpoint, the boundary tests in
`test_boundaries.py` can be unskipped.

---

## How the harness pins these

Each bug has a test that records the **current** behavior into a golden cassette
and asserts on it. The tests carry inline notes:

- `test_bulk.py::test_bulk_group_queries` — asserts the error envelope (the
  crash), with a comment explaining the `map()` bug and "if the bug is fixed,
  re-record."
- `test_errors.py::test_error_property_not_a_python_attribute` — asserts the
  `AttributeError` leak is present in the error envelope.
- `test_errors.py::test_error_ao_value_below_minimum` — uses `/json/` (where
  validation works) and comments that `/rest/` would silently no-op.
- `test_boundaries.py` (REMOVED) — the clamp mechanism is documented here in §4; the tests were dead (always-skipped) because the contract is not black-box-observable in one round-trip. Re-add as device-gated poll-to-stable tests if the clamps need exercising.

**Re-recording after a fix:** once any of these is fixed, run
`EVOK_TEST_MODE=record EVOK_BASE_URL=... uv run pytest <test>` to refresh the
cassette, then update the test's assertions to match the corrected behavior
(and move the entry from this file to a changelog).
