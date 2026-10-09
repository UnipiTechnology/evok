# Evok WebSocket API

The WebSocket API allows for two-way communication between the client and the server over an open connection. Evok sends changes to every connected client. A list of reflected devices can be defined. It is suitable for cases, where you need to immediately react to events in your application.

## Commands

The client sends a JSON object with the command in `cmd`.

| Command  | Message                                                    | Reply                                     |
|----------|------------------------------------------------------------|-------------------------------------------|
| `filter` | `{"cmd": "filter", "devices": ["do", "ao"]}`               | none                                      |
| `all`    | `{"cmd": "all"}`                                           | list of the states of all devices         |
| `full`   | `{"cmd": "full", "dev": "do", "circuit": "1_01"}`          | state of the device                       |
| `set`    | `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}` | none, the new state is sent as an event |

### filter

Sets the device types sent in events. Altnames such as `input` or `relay` can be used, unknown types are skipped.
An empty list stops the events, `["default"]` restores the default filter, which sends the events of all devices.

### all

Returns the state of all devices. With `all_filtered` enabled in the [configuration](../configs/evok_configuration.md#websocket),
only the devices passing the filter are returned, the default filter returns DI, RO, AI, AO and 1-Wire sensors.

### set

Sets the params of a device, the same params as in [REST](rest.md) are accepted and validated. The params can be passed

- in `value` as the value of the device: `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": 1}`
- in `value` as an object: `{"cmd": "set", "dev": "do", "circuit": "1_01", "value": {"value": 1, "pulse_duration": 5}}`
- as other keys of the message: `{"cmd": "set", "dev": "di", "circuit": "1_01", "debounce": 50}`

The `value` is always the param `value` of the device, e.g. the debounce of a DI must be set by `debounce`.
The `circuit` can be also an alias.

## Events

Evok sends the states of the changed devices to every client, always as a list. With a filter set by `filter`,
only the states of the device types in the filter are sent.

## Errors

An invalid request (invalid JSON, unknown command, missing `dev` or `circuit`, unknown device, invalid params)
or a device on a Modbus unit which failed its last scan (`UnitUnavailable`)
gets an error reply only to the requesting client, in the same format as REST:

```json
{"success": false, "errors": {"DeviceNotFound": "Circuit or alias with name '9_99' not defined!"}}
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
Received message: [{"dev": "ai", "circuit": "2_01", "value": 132798232.0, "unit": "Ohm", "mode": "Resistance2W", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 100000]}]
Received message: [{"dev": "ai", "circuit": "3_01", "value": -0.004, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}]
Received message: [{"dev": "ai", "circuit": "1_01", "value": 8.703, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"value": 0, "unit": "V", "range": [0, 10]}, "Current": {"value": 1, "unit": "mA", "range": [0, 20]}}, "range": [0, 10]}]
Received message: [{"dev": "ai", "circuit": "2_04", "value": -0.004, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}, {"dev": "ai", "circuit": "2_03", "value": -0.003, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}]
Received message: [{"dev": "ai", "circuit": "3_01", "value": -0.0, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}]
Received message: [{"dev": "ai", "circuit": "1_01", "value": 8.7, "unit": "V", "mode": "Voltage", "modes": {"Voltage": {"value": 0, "unit": "V", "range": [0, 10]}, "Current": {"value": 1, "unit": "mA", "range": [0, 20]}}, "range": [0, 10]}]
Received message: [{"dev": "ai", "circuit": "2_04", "value": -0.003, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}, {"dev": "ai", "circuit": "2_03", "value": -0.001, "unit": "V", "mode": "Voltage10", "modes": {"Disabled": {"value": 0}, "Voltage10": {"value": 1, "unit": "V", "range": [0, 10]}, "Voltage2V5": {"value": 2, "unit": "V", "range": [0, 2.5]}, "Current20m": {"value": 3, "unit": "mA", "range": [0, 20]}, "Resistance3W": {"value": 4, "unit": "Ohm", "range": [0, 1960]}, "Resistance2W": {"value": 5, "unit": "Ohm", "range": [0, 100000]}}, "range": [0, 10]}]
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
Received message: [{"dev": "do", "circuit": "1_01", "value": 1, "pending": false, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0}]
Received message: [{"dev": "do", "circuit": "1_04", "value": 1, "pending": false, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0}]
Received message: [{"dev": "ao", "circuit": "2_03", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}}, "value": 5.9, "unit": "V", "range": [0, 10]}]
Received message: [{"dev": "ao", "circuit": "2_04", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}}, "value": 1.3, "unit": "V", "range": [0, 10]}]
Received message: [{"dev": "do", "circuit": "1_01", "value": 0, "pending": false, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0}]
Received message: [{"dev": "do", "circuit": "1_04", "value": 0, "pending": false, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0}]
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

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
