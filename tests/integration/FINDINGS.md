# Evok — known bugs found by the integration harness

Bugs discovered while recording the black-box integration suite against Evok
v3.0.6 on a Neuron M103. Each is pinned by a test in `tests/integration/suite/`
that encodes the CURRENT (buggy) behavior so the harness passes; the tests
document the bug inline and will need re-recording once fixed.

Status legend:
  - [pinned]    harness records the buggy behavior; fix → re-record the cassette
  - [quirk]     arguably intended/by-design, but surprising; documented
  - [FIXED]     fixed in Evok 3.1, the test asserts the corrected behavior

---

## 1. [FIXED] Bulk `group_queries` / `group_assignments` crash on JSON serialization

**Status:** fixed in Evok 3.1 (`cd5622b`, the handler is `evok/bulk_handler.py`): each query of `group_queries`
returns the list of the states of its devices, in the order of the queries; `group_assignments` sets the devices.
Pinned by `tests/integration/suite/test_bulk.py::test_bulk_group_queries` (two queries, two lists).

**Originally** (v3.0.6, `evok/evok.py:329, 331, 355, 357`, `JSONBulkHandler.post`): the handler builds the response with `map(methodcaller('full'), all_devs)`
(lazy iterator) instead of `list(map(...))`. When `json.dumps(result)` runs, the
`map` object is not JSON-serializable, so the whole request fails with:

```json
{"success": false, "errors": {"TypeError": "Object of type map is not JSON serializable"}}
```

Both `group_queries` and `group_assignments` are affected (4 call sites). The
`individual_assignments` path uses a list and works.

The fix builds the lists of the states, one per query.

---

## 2. [FIXED] REST property-read leaked `AttributeError` for non-attribute `full()` keys

**Status:** fixed in Evok 3.1. `GET /rest/ai/1_01/unit` now returns HTTP 200
`{"unit": "V"}`. Pinned by `tests/integration/suite/test_errors.py::test_error_property_read_unit`.

**Originally:** `GET /rest/<dev>/<circuit>/<prop>` did `getattr(device, prop)`,
but some keys present in `device.full()` were NOT Python attributes — e.g.
`AnalogInput` exposed `unit` in `full()` via a `unit_name` property, so reading
`/rest/ai/1_01/unit` returned 404 with the raw `AttributeError`:

```json
{"success": false, "errors": {"AttributeError": "'AnalogInput' object has no attribute 'unit'"}}
```

The property-read path was inconsistent with `full()`. The fix made the `full()`
keys real attributes (option (b): `unit_name` → `unit` and the like).

---

## 3. [FIXED] REST (`/rest/*`) silently no-ops JSON POST bodies

**Status:** fixed in Evok 3.1 (`LegacyRestHandler._get_kw` in `evok/evok.py`): `/rest/*` reads a JSON object
with `Content-Type: application/json` or a body starting with `{` (as `curl -d` sends it, with the form content
type), otherwise the form; an empty body sets nothing. A JSON body which is not an object is refused with 400
on `/rest/*` and `/json/*`. The params of a JSON body are validated as on `/json/*`: `POST /rest/ao/1_01/
{"value": -1}` returns 400. The range of the schema is checked also for the strings of a form.
Pinned by `tests/integration/suite/test_errors.py::test_error_rest_silently_noops_json_body` (the name is kept
for its cassette) and `test_error_ao_value_below_minimum`.

**Originally:** `LegacyRestHandler._get_kw` reads `self.request.body_arguments` (form-encoded
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

The fix reads the JSON body on `/rest/*` too, as `LegacyJsonHandler` does.

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

- `test_bulk.py::test_bulk_group_queries` — asserts the FIXED behavior (§1): two
  queries return two lists of states.
- `test_errors.py::test_error_property_read_unit` — asserts the FIXED behavior
  (`unit` now readable, HTTP 200).
- `test_errors.py::test_error_ao_value_below_minimum` and
  `test_error_rest_silently_noops_json_body` — assert the FIXED behavior (§3): a
  value out of the range is refused with 400 on `/json/` and `/rest/`.
- `test_errors.py::test_error_ai_unknown_mode` — an unknown AI mode is refused
  with 400.
- `test_boundaries.py` (REMOVED) — the clamp mechanism is documented here in §4; the tests were dead (always-skipped) because the contract is not black-box-observable in one round-trip. Re-add as device-gated poll-to-stable tests if the clamps need exercising.

**Re-recording after a fix:** once any of these is fixed, run
`EVOK_TEST_MODE=record EVOK_BASE_URL=... uv run pytest <test>` to refresh the
cassette, then update the test's assertions to match the corrected behavior
(and move the entry from this file to a changelog).
