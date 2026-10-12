# API changes in the dev-src branch

Evok · branch `dev-src` against `main` (`b2e241c`) · up to `4003436` · 135 commits

The changes which affect the clients of REST, JSON, Bulk, WebSocket, RPC and the webhook, the configuration and
the HW definitions. The incompatible changes come first. Every change names its commits
(`https://github.com/UnipiTechnology/evok/commit/<hash>`).

## Check on a device before the release

- **Unipi nodes for Node-RED:** which `Origin` header they send to the WebSocket. If they send their own address,
  Evok refuses them with 403 and the address has to be added to `allowed_origins`.
- **nginx configuration of the package:** it has to pass the original host for the WebSocket
  (`proxy_set_header Host $host`), otherwise the web interface behind nginx gets no WebSocket.
- **Firmware and the scan after a change:** if the firmware shows a write in its registers with a delay, the reply
  to a change still has the old state, the next scan corrects it.

## Incompatible changes

### Access to the API

- The default address of the API is `127.0.0.1`, before all interfaces. An empty `address` still listens on all
  of them. — `5b81429`
- CORS is sent only to the origins of `allowed_origins`, before `*` to all. A WebSocket from a browser of another
  origin gets 403. — `2b7f668`
- The body of a request is limited to 1 MB, a message of a WebSocket client to 64 kB. — `ba4212f`, `053da5d`

### Devices and their state

- **Watchdog:** — `6ac4eb0`, `f298e87`, `fce8d1d`
  - its circuit is the name of the unit (`1`) instead of `1_01`, the saved aliases of watchdogs are not assigned,
  - `nv_save` returns an error and is not in `full()`,
  - `value` is 0/1 instead of 0–3, a restart is reported only by `was_wd_reset`.
- **AI and AO:** `modes` has only `unit` and `range`, without the code of the register and the `transformation`.
  — `e792e17`
- **OwPower:** `value` is always 0/1, before `true`/`false` after a write. — `2042b3d`
- **DI:** `ds_mode` out of the `DirectSwitch` mode returns an error, before it was silently ignored. — `96f66c6`
- **PWM:** the hardware PWM refuses a frequency above 50 kHz. Another division of the frequency: other register
  values, a more precise frequency and a finer duty. — `a05718c`
- **Invalid values are refused** instead of being processed silently: NaN and infinity, the value `'2'` of an
  output, an AO out of its range (before it was clamped), an unknown mode of a DI. — `1a6910c`, `891bd4a`, `5f15f41`
- NaN and infinite values of AIs and data points are returned as the strings `'NaN'`, `'Infinity'`, `'-Infinity'`.
  — `5f15f41`
- `last_comm` of a unit is `null` before the first communication, before about 1.7e9 s. — `2f323f0`
- **1-Wire sensors of the configuration:** no `lost: true` event right after the start or a reconnection to owserver,
  a sensor is read after the bus finds it. A sensor which the search of the bus has not found is reported lost.
  — `5fa3eca`
- **RO, DO, LED:** no `pulse_duration`, `timeout` (DO) and `pending`, a pulse is set by the sequencer of the output
  (`/rest/sequencer/<type>_<circuit>`, `running` instead of `pending`). While it runs, a change of the output
  except its alias is refused with 409 (RPC `-32002`), cancel it by the sequencer first. The RPC methods
  `*_set_for_time` and `output_get` stay. — `a85fb14`, `57492fe`

### Circuits by the HW definitions

- The relays 17–28 of M403/L403 have the circuits `1_17`…`1_28`, before they replaced the relays 1–12. — `50da3b3`
- The inputs and outputs 17–32 of one feature read the next register. — `b71adde`, `50da3b3`
- Data points with `count > 1` and a 32-bit type take two registers each, so their circuits differ. — `50da3b3`

### REST and JSON

- Error statuses: 404 unknown device, 400 invalid data, 401 missing or invalid token, 403 a change with the read-only
  token, 503 unavailable unit, 500 internal error. — `4b36483`, `a3f4679`, `9f9482c`
- `POST /rest/all` returns 405, a POST with another part of the URL than `/alias` returns 404. — `3c8f58e`, `34bdcd2`
- The alias `all` is reserved, an alias has at most 64 characters. — `34bdcd2`, `3bae093`

### Bulk

- The assignments are done by Modbus units, not in the order of the request. An error returns the results of the
  units done and of the assignments of its unit before it. — `a3f4679`
- The `global_device_id` filter was removed. — `6cd0802`

### WebSocket

- Only the commands `all`, `filter`, `full`, `set`. Before any method of a device could be called. — `8e72731`
- Events are always a list. A slow client gets merged changes, it can miss a short pulse. — `7f827fa`, `053da5d`

### RPC

- `ao_set` takes `mode` instead of the frequency, the `ai_set*` methods were removed. — `af3982c`
- Error codes: invalid params `-32602`, unavailable unit `-32000`, a change with the read-only token `-32001`,
  internal error `-32603` without the text of the exception. — `cb94d9f`, `c8a92a4`, `4003436`

### Other

- `print_log` of `modbus_slave` was replaced by `GET /log`. — `54fe858`

## New features

- **Security:** an optional `token` for all APIs (Bearer, Basic, `?token=` for the WebSocket) and `allowed_origins`.
  — `763016c`, `2b7f668`
- **Read-only token:** an optional `read_token` (requires `token`). It allows reading by REST and JSON, the queries
  of bulk, `all`, `full`, `filter` and the events of the WebSocket, the reading methods of RPC and `/log`. A change of
  a device returns 403 `ReadOnlyAccess`, by RPC `-32001`; a bulk with a change is refused as a whole. — `4003436`
- `GET /log?lines=N` returns the end of the log. — `54fe858`
- `POST /modbus_slave/{circuit}` with `scan_enabled` and the alias. `full()` returns `scan_enabled` and `scan_error`.
  — `2319b2b`, `96ba320`, `d1add77`
- Data points can be written by `writable`, `full()` returns it. — `eb4eda5`, `e792e17`
- **Sequencer** of each output (RO, DO, LED), the device `sequencer` with the circuit `<type>_<circuit>`
  (`/rest/sequencer/do_1_01`): a pulse (`value`, `pulse_duration`), a sequence of the changes of the output
  (`steps`, `final`) or `cancel`; its state has `running` and the progress, an event at the start, steps and end.
  The RPC method `relay_set_for_time`. — `e16a3bf`, `7789635`, `a85fb14`
- The reply to POST, bulk and the WebSocket `set` has the state after the writes and the event comes at once.
  — `a3f4679`
- **New events:** — `60e2287`, `08d9f56`, `62b37ef`, `891bd4a`
  - a changed alias of a device on a Modbus unit,
  - a lost and a restored communication with a unit,
  - a change of `counter_mode`, the mode and the debounce of a DI.
- A successful bulk reply has `"success": true`. — `ba4212f`
- Deleting the alias of a device which is not connected by `POST /rest/run/alias` with `delete`. — `b7cebd6`
- `GET /rest/serial_bus/{bus}` and `/rest/tcp_bus/{bus}` return the configuration of a Modbus bus and its devices,
  before a 500 error. The buses are read-only and not in `/rest/all`. — `b40a57c`
- **Configuration:** `apis.rpc.enabled`, `min_interval` of the webhook, `timeout`, `connect_timeout` and `retries`
  of the buses. — `f7ebda1`, `0044241`, `16463d5`, `a6ede44`
- **Outputs without coils:** RO, DO and LED without `val_coil` write their bit of `val_reg` (a holding register),
  e.g. a unit which has no coils. A DO without the PWM registers is a simple output, `modes` is optional. — `05ad76c`

## Deprecated

- `counter_mode` and `counter_modes` of a DI. `Disabled` only reports the counter as 0, the mode is not saved.
  — `a5d8065`
- The param `timeout` of the RPC method `output_set_for_time` is an alias of `pulse_duration`. — `e16a3bf`
- `nv_sav_coil` of the WD feature is not used, the settings are saved by the NV_SAVE feature. — `f298e87`
- `frequency` of a register block is a deprecated alias of `scan_divider`, a warning is logged, both in one block
  are an error. The value is a divider of the scans, not a frequency. — `d95f57a`
- The REGISTER feature of the HW definitions, a warning is logged. A DATA_POINT with `datatype: uint16` replaces it,
  its devices are `data_point` instead of `register`, without `_inp` in the circuit of an input register. — `fec507a`, `97ca903`

## Configuration and HW definitions

An invalid value is an error: the unit or the feature is not created and the error is logged.

- **Tokens:** `token` and `read_token` must be non-empty strings, `read_token` requires `token` and must differ from
  it; `allowed_origins` is a list of http/https origins. Otherwise Evok does not start.
  — `763016c`, `2b7f668`, `4003436`
- **Unit:** `scan_frequency` > 0, `scan_enabled` only `true`/`false`, `slave-id` 1–247 on RTU and 0–255 on TCP.
  — `d1add77`, `96ba320`
- **Register blocks:** at most 125 registers, addresses up to 65535, no overlaps. — `2f323f0`, `9f9482c`
- **Modbus devices:** the name must be unique over all buses. The second device with the same name is not
  created, before it replaced the first one in the API and its IOs were missing. — `d8acc38`
- **Unit which does not respond:** it is probed by one request with `probe_timeout` of the bus (0.1 s on RTU)
  without the retries, before every attempt locked the bus for `(retries + 1) * timeout` (1 s by default)
  and the other units of the bus waited. — `30cb46f`
- **Modbus addresses:** a serial port can be used by one `MODBUSRTU` bus only, the `slave-id` must be unique on an RTU
  bus and on a TCP server (`hostname`, `port`) over all `MODBUSTCP` buses. The second bus or device is not created,
  before both read and wrote the same unit. — `dc7b1ee`
- **Circuits:** a duplicate circuit is an error of the feature, `start_index` applies also to RO, DO and LED.
  — `50da3b3`
- **Modes:** the `value` of a mode must be a unique integer, the datatype of an AI `transformation` must be known.
  — `e005aa4`, `a053e80`
- **Data points:** a writable data point in an input register is an error. — `e792e17`
- **Watchdog:** one per unit, `count` is not used. — `6ac4eb0`
- **1-Wire:** the type `DS2404` is not supported, it has no PIO and was always lost. The `address` of a sensor
  is found also without the CRC, the dots or in lower case. `scan_interval: 0` searches the bus only after
  the connection and on request, before once per hour; a changed `scan_interval` applies at once. — `4ecdf2f`
- **OWFS buses:** the name of a 1-Wire sensor must be unique over all OWFS buses, a duplicate configured sensor
  is not created, a found one is skipped; before the second sensor replaced the first one in the API. — `fa35a94`
- **OWFS bus by the kernel:** the sensors are read by the 1-Wire subsystem of the kernel (`/sys/bus/w1`), owserver
  and asyncowfs are not used. The option `master` (`w1_bus_master1`, the first one by default) instead of
  `hostname` / `port`, the status of the bus has `master`. The address and the circuit of a found sensor stay
  the same. The `value` of a DS2406 is the state of its channel flip-flops. With the udev rule
  `etc/udev/rules.d/60-evok-w1.rules` `do_scan` forces a search and the thermometers are converted at once.
  — `776b371`, `2bb5167`

## Runtime and installation

- Python 3.12, `tmodbus` instead of `pymodbus`. — `862d760`, `733871c`
- 1-Wire by the kernel: the driver of the master (e.g. `ds2482`) and the modules of the sensors instead of
  the package `owserver`; no dependency `asyncowfs` and `anyio`. The package should install the udev rule
  `etc/udev/rules.d/60-evok-w1.rules` (group `evok`). — `776b371`, `9790404`, `2bb5167`
- The options `--config-dir` and `--alias-file` (variables `EVOK_CONFIG_DIR`, `EVOK_ALIAS_FILE`). Without
  `config.yaml` Evok exits with an error. — `af85489`

---

Compiled from the messages of 135 commits between `main` and `dev-src` (up to `4003436`) and from the changes of
the API documentation. The code of `main` was not compared line by line, details which the commit messages do not
describe may be missing.
