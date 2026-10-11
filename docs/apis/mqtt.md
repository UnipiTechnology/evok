# Evok MQTT API

Evok publishes the states of the devices to an MQTT broker and receives the commands from it. It is suitable
for home automation systems and integration platforms which use a broker, e.g. Home Assistant or Node-RED.
The API is disabled by default, see the [configuration](../configs/evok_configuration.md#mqtt).

Evok is a client of a broker, it does not include one. A local broker can be installed by `apt install mosquitto`.

## Topics

The topics start with the `prefix` of the configuration, `evok` by default. More units on one broker use their own
prefix, e.g. `evok/boiler-room`.

| Topic                            | Direction  | Payload                                                         |
|----------------------------------|------------|-----------------------------------------------------------------|
| `<prefix>/status`                | from Evok  | `online` / `offline`, retained                                  |
| `<prefix>/<device>/<circuit>`    | from Evok  | the state of the device as JSON, retained                       |
| `<prefix>/<device>/<circuit>/set`| to Evok    | the parameters of the change                                     |
| `<prefix>/error`                 | from Evok  | the error of a command, not retained                            |

- `<device>` is the device type as in the REST API (`di`, `ro`, `do`, `ai`, `ao`, `led`, `sensor`, `watchdog`, ...),
  `<circuit>` is the [circuit](../circuit.md) of the device. The alias of a device is in its state.
- **The state** is the same as the reply of `GET /json/<device>/<circuit>`. Evok publishes it after every change
  of the device and the states of all devices after the connection to the broker. The states are retained,
  a new client gets the actual state of all devices at once. The changes are merged as for the WebSocket,
  the last state of each device is published.
- **The status** is `online` after the connection. `offline` is published when Evok stops and by the broker
  as the last will when the connection is lost, e.g. a power failure of the unit.
- `device_mask` of the configuration selects the published device types.

## Commands

A message to `<prefix>/<device>/<circuit>/set` changes the device:

- a JSON object is the parameters as the body of `POST /json/<device>/<circuit>`,
  e.g. `{"value": 1}` or `{"alias": "light"}`; a pulse is set by the [sequencer](./sequencer.md) of the output,
  e.g. `evok/sequencer/ro_1_01/set` with `{"value": 1, "pulse_duration": 2}`,
- another value is the value of the device, e.g. `1`, `0`, `true` or `21.5` (`{"value": ...}`).

The parameters are validated as for REST. The new state is published as the state of the device.
A Modbus unit which does not respond refuses the change, an output refuses it while its sequencer runs.
An error is published to `<prefix>/error`:

```json
{"topic": "evok/ro/1_01/set", "success": false, "errors": {"DeviceNotFound": "Circuit or alias with name '1_01' not defined!"}}
```

With `read_only: true` Evok does not subscribe the commands.

## Security

The access is controlled by the broker: the user and the password of the configuration, an ACL of the broker
for the topics of the prefix and TLS for a broker on the network. The `token` of the other APIs is not used.
Evok logs a warning at the start if it accepts the commands and has no user of the broker. A client which
can publish to `<prefix>/+/+/set` controls the devices of the unit.

## Examples

The examples use the clients of the package `mosquitto-clients`.

### Reading the states

```bash title="Bash"
mosquitto_sub -h 127.0.0.1 -v -t 'evok/#'
```

```
evok/status online
evok/ro/1_01 {"dev": "ro", "circuit": "1_01", "value": 0}
evok/di/1_01 {"dev": "di", "circuit": "1_01", "value": 1, "debounce": 50, ...}
```

### Changing a device

```bash title="Bash"
# switch the relay on
mosquitto_pub -h 127.0.0.1 -t evok/ro/1_01/set -m 1
# switch it on for 2 seconds
mosquitto_pub -h 127.0.0.1 -t evok/sequencer/ro_1_01/set -m '{"value": 1, "pulse_duration": 2}'
```

### Python

The example uses the package `aiomqtt` (`pip3 install aiomqtt`).

```python title="Python"
import asyncio
import json

import aiomqtt


async def main():
    async with aiomqtt.Client('127.0.0.1') as client:
        await client.subscribe('evok/di/+')
        await client.publish('evok/sequencer/ro_1_01/set', json.dumps({'value': 1, 'pulse_duration': 2}))
        async for message in client.messages:
            state = json.loads(message.payload)
            print(state['circuit'], state['value'])


asyncio.run(main())
```
