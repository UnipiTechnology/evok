# Evok WebSocket API

The WebSocket API allows for two-way communication between the client and the server over an open connection. Evok sends changes to every connected client. A list of reflected devices can be defined. It is suitable for cases, where you need to immediately react to events in your application.

## Connection

The WebSocket is at `ws://<host>:8080/ws`, the route exists only with `enabled: true` in the
[configuration](../configs/evok_configuration.md#websocket) (`false` by default). With a `token`
in the configuration it is required in the header `Authorization: Bearer <token>`, a browser sends it as `ws://<host>:8080/ws?token=<token>`. A web page
in a browser can connect only from the address of Evok or from `allowed_origins`, see [Security](../security.md).
With the `read_token` the command `set` gets the error `ReadOnlyAccess`.

Evok sends a ping every 10 s and closes a connection without a pong within 10 s, e.g. after a lost network.
A message of a client can have at most 64 kB.

## Events

The changed devices are sent as a list of their states. While a message is being sent to a slow client,
the next changes are merged and sent in the next message with the last state of each device,
a short change between two messages (e.g. a pulse of an input) can be missed by a slow client.

## Commands

The client sends a JSON object with the command in `cmd`.

| Command  | Message                                                    | Reply                                     |
|----------|------------------------------------------------------------|-------------------------------------------|
| `filter` | `{"cmd": "filter", "devices": ["do", "ao"]}`               | none                                      |
| `all`    | `{"cmd": "all"}`                                           | list of the states of all devices         |
| `full`   | `{"cmd": "full", "dev": "do", "circuit": "1_01"}`          | state of the device                       |
| `set`    | `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}` | none, the new state is sent as an event |

### filter

Sets the device types sent in events. Altnames such as `input` or `relay` can be used, unknown types are skipped;
a list of only unknown types is refused with `ValueError`. An empty list stops the events, a list starting with
`"default"` restores the default filter, which sends the events of all devices.

### all

Returns the state of all devices, without `all_filtered` of all device types, also of the sequencers, `run`
and the Modbus buses (`serial_bus`, `tcp_bus`), which `/rest/all` leaves out. With `all_filtered` enabled
in the [configuration](../configs/evok_configuration.md#websocket), only the devices passing the filter are returned, the default filter returns DI, RO, AI, AO and 1-Wire sensors.

### set

Sets the params of a device, the same params as in [REST](rest.md) are accepted and validated. The params can be passed

- in `value` as the value of the device: `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}`
- in `value` as an object: `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": {"value": 1, "alias": "pump"}}`
- as other keys of the message: `{"cmd": "set", "dev": "di", "circuit": "1_01", "debounce": 50}`

The `value` is always the param `value` of the device, e.g. the debounce of a DI must be set by `debounce`.
The `circuit` can be also an alias.

## Events

Evok sends the states of the changed devices to every client, always as a list. With a filter set by `filter`,
only the states of the device types in the filter are sent.

The state of a device of a Modbus unit and of a 1-Wire sensor has `comm` (`ok`, `timeout`, `error`) and `last_comm`
(seconds since the last successful communication with the unit). The `comm` of a 1-Wire sensor is only `ok`
or `timeout` (the sensor is lost), never `error`. Its `time` is deprecated, it is the time of the event loop
(a monotonic clock) of the last read, use `last_comm`. When the unit stops responding or responds again,
the states of all its devices are sent, `value` keeps the last known value and `comm` tells if it is valid.

## Errors

An invalid request (invalid JSON, unknown command, missing `dev` or `circuit`, unknown device, invalid params)
or a device on a Modbus unit which failed its last scan (`UnitUnavailable`) or a failed request of the change
(`UnitCommunicationError`)
gets an error reply only to the requesting client, in the same format as REST:

```json
{"success": false, "errors": {"DeviceNotFound": "Circuit or alias '9_99' with devtype 'do' not found"}}
```

## Examples

For python examples you need installed `websocket-client` package. You can install it with this command: `pip3 install websocket-client`.

### Listening on WebSocket without filter

```python title="Python"
import websocket


def on_message(ws, message):
    print(f"Received message: {message}")


def on_close(ws, status, message):
    print(f"WebSocket connection closed")

    
def on_open(ws):
    print("WebSocket connection opened")

    
if __name__ == "__main__":
    url = 'ws://127.0.0.1:8080/ws'
    ws = websocket.WebSocketApp(url, on_message=on_message, on_close=on_close, on_open=on_open)
    ws.run_forever()
```

```text title="Output"
WebSocket connection opened
Received message: [{"dev": "ai", "circuit": "2_01", "value": 132798232.0, "unit": "Ohm", "mode": "Resistance2W", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 100000], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "3_01", "value": -0.004, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "1_01", "value": 8.703, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}, "Current": {"unit": "mA", "range": [0, 20]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "2_04", "value": -0.004, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}, {"dev": "ai", "circuit": "2_03", "value": -0.003, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "3_01", "value": -0.0, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "1_01", "value": 8.7, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}, "Current": {"unit": "mA", "range": [0, 20]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ai", "circuit": "2_04", "value": -0.003, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}, {"dev": "ai", "circuit": "2_03", "value": -0.001, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {}, "Voltage10": {"unit": "V", "range": [0, 10]}, "Voltage2V5": {"unit": "V", "range": [0, 2.5]}, "Current20m": {"unit": "mA", "range": [0, 20]}, "Resistance3W": {"unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
...
```

### Listening on WebSocket with filter on 'do' and 'ao'

```python title="Python"
import websocket, json


def on_message(ws, message):
    print(f"Received message: {message}")


def on_close(ws, status, message):
    print(f"WebSocket connection closed")

    
def on_open(ws):
    print("WebSocket connection opened")
    msg = {"cmd": "filter", "devices": ["do", "ao"]}
    ws.send(json.dumps(msg))

    
if __name__ == "__main__":
    url = 'ws://127.0.0.1:8080/ws'
    ws = websocket.WebSocketApp(url, on_message=on_message, on_close=on_close, on_open=on_open)
    ws.run_forever()
```

```text title="Output"
WebSocket connection opened
Received message: [{"dev": "do", "circuit": "1_01", "value": 1, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0, "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "do", "circuit": "1_04", "value": 1, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0, "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ao", "circuit": "2_03", "value": 5.9, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "ao", "circuit": "2_04", "value": 1.3, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}}, "range": [0, 10], "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "do", "circuit": "1_01", "value": 0, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0, "comm": "ok", "last_comm": 0.041}]
Received message: [{"dev": "do", "circuit": "1_04", "value": 0, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0, "comm": "ok", "last_comm": 0.041}]
...
```

### Setting DO

DO 1.01 will be set to HIGH.

```python title="Python"
import websocket, json


def on_message(ws, message):
    print(f"Received message: {message}")

    
def on_close(ws, status, message):
    print(f"WebSocket connection closed")

    
def on_open(ws):
    print("WebSocket connection opened")
    msg = {"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}
    ws.send(json.dumps(msg))
    print("WebSocket send DO 1.01 to HIGH")
    ws.close()

    
if __name__ == "__main__":
    url = 'ws://127.0.0.1:8080/ws'
    ws = websocket.WebSocketApp(url, on_message=on_message, on_close=on_close, on_open=on_open)
    ws.run_forever()
```

```text title="Output"
WebSocket connection opened
WebSocket send DO 1.01 to HIGH
WebSocket connection closed
```

### Node-RED

The nodes `websocket in` and `websocket out` share one client config node. Its URL must begin with
`ws://` (or `wss://`): with another scheme, e.g. `http://`, Node-RED treats the config node as a server
and never connects to Evok. With Node-RED on the controller use `ws://127.0.0.1:8080/ws`.

The package
[@unipitechnology/node-red-contrib-unipi-evok](https://github.com/UnipiTechnology/node-red-contrib-unipi-evok)
adds the nodes `unipi input v3` and `unipi output v3`, which filter the received events by the device and
the circuit and build the commands. A minimal flow shows the state of DO 1.01 in a debug node and switches
it by two inject nodes:

```json title="Flow"
[{"id":"f6f2187d.f17ca8","type":"tab","label":"Flow 1","disabled":false,"info":""},{"id":"63c73b21cf141ec1","type":"websocket in","z":"f6f2187d.f17ca8","server":"","client":"a5816cadf9fadfc3","x":320,"y":500,"wires":[["f8797146eb445745"]]},{"id":"1fa70a98c26f663d","type":"websocket out","z":"f6f2187d.f17ca8","server":"","client":"a5816cadf9fadfc3","x":720,"y":600,"wires":[]},{"id":"2ab9d28f8d2580bb","type":"inject","z":"f6f2187d.f17ca8","name":"DO 1.01 - High","props":[{"p":"payload"},{"p":"topic","vt":"str"}],"repeat":"","crontab":"","once":false,"onceDelay":"","topic":"","payload":"1","payloadType":"num","x":300,"y":580,"wires":[["d1eb07a242573789"]]},{"id":"332cfa0214d8e6ff","type":"inject","z":"f6f2187d.f17ca8","name":"DO 1.01 - Low","props":[{"p":"payload"},{"p":"topic","vt":"str"}],"repeat":"","crontab":"","once":false,"onceDelay":"","topic":"","payload":"0","payloadType":"num","x":290,"y":620,"wires":[["d1eb07a242573789"]]},{"id":"adc4db639f25af50","type":"debug","z":"f6f2187d.f17ca8","name":"DO 1.01 - State","active":true,"tosidebar":true,"console":false,"tostatus":true,"complete":"payload","targetType":"msg","statusVal":"payload.value","statusType":"msg","x":720,"y":500,"wires":[]},{"id":"f8797146eb445745","type":"unipi-input-v3","z":"f6f2187d.f17ca8","name":"DO 1.01","alias":"","devices":"do","circuits":"1.01","x":540,"y":500,"wires":[["adc4db639f25af50"]]},{"id":"d1eb07a242573789","type":"unipi-output-v3","z":"f6f2187d.f17ca8","name":"DO 1.01","cmd":"set","alias":"","devices":"do","circuits":"1.01","enableFil":"1","x":500,"y":600,"wires":[["1fa70a98c26f663d"]]},{"id":"a5816cadf9fadfc3","type":"websocket-client","path":"ws://127.0.0.1:8080/ws","tls":"","wholemsg":"false","hb":"0","subprotocol":"","headers":[]},{"id":"ace7c022b041d7ce","type":"global-config","env":[],"modules":{"@unipitechnology/node-red-contrib-unipi-evok":"0.0.8"}}]
```

The flow receives a message only when a device changes, an inject node with the payload `{"cmd": "all"}`
wired to `websocket out` requests the state of all devices at once, see [Commands](#commands).

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
