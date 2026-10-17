# Mock device bus (functional tier, no hardware)

The functional tier runs the **real evok server** against **fake buses** so
routing, validation, dispatch, serialization, auth, and error handling are
exercised without hardware. This is NOT a mock of the server — these are
stand-ins on the *bus* side: a fake Modbus TCP server (the PLC) and a fake
kernel 1-Wire sysfs tree (the 1-Wire bus).

## Architecture

```
real evok server  ──Modbus TCP──►  mockbus (fake PLC, 2 boards)
(127.0.0.1:8090)                    (127.0.0.1:5020)
       │
       │ /sys/bus/w1/devices (private mount namespace)
       ▼
fake 1-Wire sysfs (DS18B20)
       │
       │ HTTP/WS/RPC
       │
   harness (pytest, EVOK_TEST_MODE=functional)
```

Both fakes are driven by the **same hw_definition YAMLs the real device uses**
(copied verbatim from `/etc/evok/hw_definitions/`):
- `00.yaml` — CPU board (slave-id 1): 4 DI, 4 DO, 1 AI, 1 AO, 4 LED, WD, owpower
- `01.yaml` — relay board (slave-id 2): 8 DI, 8 RO, 1 WD

The mockbus serves both slave-ids on one TCP port and mirrors coil writes into
the holding-register bitmask so evok's scan detects transitions (this is how
WS/REST change events fire without real hardware). The fake 1-Wire tree serves a
DS18B20 at the address of the sensor tests (`suite/test_sensor.py`), as plain files
under `/sys/bus/w1/devices` (the layout evok's `evok/w1/sysfs.py` reads).

## Run it

The mockbus + fake 1-Wire + evok lifecycle is managed by a **standalone launcher**,
not by pytest. Run it in one terminal, then point the harness at it from another:

```bash
# terminal 1: start mockbus + fake 1-Wire sysfs + evok (foreground; Ctrl-C stops all)
cd tests/integration
uv run python mockbus/start.py

# terminal 2: run the harness against it (functional = live mode vs the URL)
EVOK_TEST_MODE=functional EVOK_BASE_URL=http://127.0.0.1:8090 uv run pytest
```

The harness stays a pure black-box client — it never launches processes.
`EVOK_TEST_MODE=functional` behaves exactly like `live` against the given URL.

The launcher re-execs itself in a private mount namespace (`unshare -rm`, no
root required) and mounts the fake tree over `/sys/bus` there. The real evok runs
as its child and inherits the namespace. `unshare` (util-linux) must be
available; on Ubuntu 24.04 CI the AppArmor restriction on unprivileged user
namespaces is disabled first (see the workflow).

## What the mock exposes

The full Neuron M103 inventory (`fixtures/devices.yaml`):

| devtype | circuits | source |
|---------|----------|--------|
| di | 2_01–2_08, 1_01–1_04 (12) | `01.yaml` (board 2) + `00.yaml` (board 1) |
| ro | 2_01–2_08 (8) | `01.yaml` |
| do | 1_01–1_04 (4) | `00.yaml` |
| ai | 1_01 (1) | `00.yaml` |
| ao | 1_01 (1) | `00.yaml` (BAO) |
| led | 1_01–1_04 (4) | `00.yaml` |
| wd | 1, 2 (2) | both boards |
| nv_save | 1, 2 (2) | both boards (`NV_SAVE`) |
| owpower | 1 (1) | `00.yaml` |
| owbus | OWBUS (1) | fake 1-Wire sysfs |
| temp | 28CD79A90800004A (1) | fake 1-Wire sysfs (DS18B20) |

