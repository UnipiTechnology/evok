# Evok black-box integration harness

Validates the **externally observable** behavior of a running Evok server over its
network APIs (REST / JSON / Bulk / RPC / WebSocket / Webhook). Server-agnostic:
imports no server code, treats the server as a black box.

## The definition of the API

Every device state in a reply (REST, JSON, bulk, RPC, WebSocket) and the params of
every accepted POST are validated against the **OpenAPI document of Evok**, generated
from the schemas of its sources (`python -m evok.openapi`, see `oracles/contract.py`).
The harness runs the generator as a subprocess of the Evok project, it does not import it.
`EVOK_OPENAPI=<file>` uses another document, e.g. the one attached to a release, to check
a device with that version.

The tests add their own assertions:

| Tests | What |
|-------|------|
| `test_rest`, `test_json`, `test_writes`, `test_bulk`, `test_rpc`, `test_ws` | the reads and the writes by each API |
| `test_errors` | the statuses and the envelopes of the errors |
| `test_invariants` | the same state by REST, JSON, RPC and WebSocket |
| `test_sequencer` | a pulse, a sequence, cancel, 409 / RPC -32002 / WS error of a change of the output while its sequence runs, the checks of a request |
| `test_auth` | 401 without a token, the `read_token` only reads (403, RPC -32001, WS), `/version` without a token; skipped when the server requires no token |
| `test_comm` | `comm` and `last_comm` of the devices, a unit which does not respond (`scan_error`) |
| `test_aliases` | set, address by the alias, list, remove, delete, the invalid and duplicate aliases |
| `test_sensor` | the 1-Wire sensor by REST and RPC |
| `test_mqtt` | the retained states, the status, the commands and their errors, the Home Assistant discovery; with `EVOK_MQTT` |
| `test_webhook` | the posted changes, only the masked device types; with `EVOK_WEBHOOK_CONFIGURED=1` |

## How to use

**Against the mockbus** — the real evok with fake buses, no hardware:

```bash
# terminal 1: start mockbus + fake 1-Wire + MQTT broker + evok (Ctrl-C stops all)
uv run python mockbus/start.py

# terminal 2: run the harness against it
EVOK_BASE_URL=http://127.0.0.1:8090 EVOK_MQTT=127.0.0.1:1884 EVOK_WEBHOOK_CONFIGURED=1 \
    uv run pytest
```

The harness sends the token of the mockbus (`mockbus/config.py`), `EVOK_TOKEN` and
`EVOK_READ_TOKEN` set the tokens of another server; a server without a token ignores them.

**Against a device** with the inventory of the mockbus (a Neuron M103, see
`fixtures/devices.yaml`) and nothing connected, the tests switch its outputs:

```bash
EVOK_BASE_URL=http://<device>:8080 uv run pytest
```

`EVOK_BASE_URL` defaults to `http://127.0.0.1:8080`.

## CI

`.github/workflows/integration-tests.yml` starts the mockbus with evok and runs the
harness against it (the job **functional**); it catches the regressions of the server
stack — routing, dispatch, serialization, validation, errors — and every deviation of
a reply from the definition of the API.

## The mockbus

`mockbus/` provides fake buses so the **real evok** can run without hardware:

- **mockbus** (`server.py`) — fake Modbus TCP server, two slave-ids, driven by the
  real `00.yaml` (CPU board) + `01.yaml` (relay board) hw_definitions. Mirrors coil
  writes into holding-register bits so scan-cache transitions fire events.
- **fake 1-Wire sysfs** (`w1sysfs.py`) — a DS18B20 tree mounted at
  `/sys/bus/w1/devices` inside a private mount namespace.
- **MQTT broker** (amqtt) of the MQTT API at 127.0.0.1:1884.
- **launcher** (`start.py`) — starts mockbus:5020 + fake 1-Wire sysfs + the broker + evok:8090,
  with the tokens, the webhook to the receiver of the tests and a unit which does not respond
  (`config.py`).

See `mockbus/README.md`.
