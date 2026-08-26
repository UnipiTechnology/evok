# Evok black-box integration & regression harness

Validates the **externally observable** behavior of the Evok server over its
network APIs (REST / JSON / Bulk / RPC / WebSocket / Webhook). Server-agnostic:
imports no server code, treats the server as a black box.

## What runs in CI

Two gates, both hardware-free, in `.github/workflows/integration-tests.yml`:

| Job | What it does | Catches |
|-----|--------------|--------|
| **replay** | Serves golden cassettes offline; validates each response against `spec/spec.json` | the offline toolchain stays self-consistent — spec generator, oracles, contract validator, and cassettes agree with each other |
| **functional** | Starts the **real evok** against the **mockbus** (fake Modbus PLC + fake 1-Wire owserver), runs the harness as a client | regressions in the server stack itself — routing, dispatch, serialization, validation, errors |

## How to use locally

**Iterating on evok code** — exercise the real server against the fake buses, no hardware:

```bash
# terminal 1: start mockbus + owserver + evok (Ctrl-C stops all)
uv run python mockbus/start.py

# terminal 2: run the harness against it
EVOK_TEST_MODE=functional EVOK_BASE_URL=http://127.0.0.1:8090 uv run pytest
```

**Offline check (no server needed)** — what CI runs for replay:

```bash
uv run pytest
```

**Updating the golden cassettes** — when evok behavior intentionally changes,
re-record from a real device, then regenerate the spec:

```bash
EVOK_TEST_MODE=record EVOK_BASE_URL=http://<device>:8080 uv run pytest
uv run python tools/extract_spec_from_cassettes.py   # regenerates spec/spec.json
```

**Checking a device for drift** — diff a running device against its cassettes:

```bash
EVOK_TEST_MODE=compare EVOK_BASE_URL=http://<device>:8080 uv run pytest
```

## How it works

The harness is built around a **frozen snapshot** of what the server did at
record time:

```
real hardware ──record──► cassettes ──generate──► spec  (committed, frozen)
                          (fixtures/golden/)     (spec/spec.json)
```

The spec is generated from the cassettes, then both are committed. Each mode
then compares something against that frozen snapshot:

| Mode | Bus behind server | Judge | Catches |
|------|-------------------|-------|---------|
| **replay** | none (offline) | spec | tooling drift — spec generator, oracles, contract validator, and cassettes stay mutually consistent |
| **functional** | fake (mockbus + owserver) | test assertions | server logic regressions — routing, dispatch, serialization, errors |
| **compare** | real device | per-field diff vs cassettes | device behavioral drift — every field, with epsilon for floats |

**Why replay isn't tautological.** The spec is **frozen and committed**: if the
generator, oracles, contract validator, or a cassette is later edited, replay
fails — it proves the offline toolchain still agrees with itself. It does **not**
catch server regressions (the server isn't running); functional and compare do.

- **Cassettes** (`fixtures/golden/`) — recorded request→response pairs, one JSON
  file per test. The regression oracle.
- **Spec** (`spec/spec.json`) — JSON Schema per device type, **generated from the
  cassettes** (not hand-authored). Regenerate with
  `tools/extract_spec_from_cassettes.py` after re-recording.

## Modes

Selected by `EVOK_TEST_MODE`; `EVOK_BASE_URL` selects the target (default
`http://127.0.0.1:8080`).

| Mode | Needs | Use |
|------|-------|-----|
| `replay` (default) | nothing | offline CI; proves spec/cassettes/tooling agree |
| `functional` | mockbus launcher | local dev; exercises real evok vs fake buses (also CI) |
| `live` | a running server | ad-hoc checks |
| `record` | a real device | refresh cassettes after intentional changes |
| `compare` | a real device | behavioral drift vs the recording (per-field diff) |

## The mockbus

`mockbus/` provides fake buses so the **real evok** can run without hardware:

- **mockbus** (`server.py`) — fake Modbus TCP server, two slave-ids, driven by the
  real `00.yaml` (CPU board) + `01.yaml` (relay board) hw_definitions. Mirrors coil
  writes into holding-register bits so scan-cache transitions fire events.
- **fake owserver** (`owserver.py`) — serves a DS18B20 over the OWFS protocol.
- **launcher** (`start.py`) — starts mockbus:5020 + owserver:4304 + evok:8090.

See `mockbus/README.md`.
