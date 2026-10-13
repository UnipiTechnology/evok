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
{"topic": "evok/ro/1_01/set", "success": false, "errors": {"DeviceNotFound": "Circuit or alias '1_01' with devtype 'ro' not found"}}
```

With `read_only: true` Evok does not subscribe the commands.

## Home Assistant

With `ha_discovery: true` Evok announces its devices to Home Assistant by the
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery). Home Assistant with its MQTT
integration on the same broker creates the entities, no configuration of Home Assistant is needed.

| Evok                            | Home Assistant                                                    |
|---------------------------------|-------------------------------------------------------------------|
| `di`                            | `binary_sensor`                                                   |
| `ro`, `do`, `led`               | `switch`, `binary_sensor` with `read_only`                        |
| `ai`                            | `sensor` with the unit of the mode                                |
| `ao`                            | `number` with the range of the mode, `sensor` with `read_only`    |
| `data_point`                    | `sensor`, a writable one `number`                                 |
| `sensor` DS18B20, DS18S20       | `sensor` of the temperature                                       |
| `sensor` DS2438                 | `sensor` of the temperature, the humidity, VDD and VAD            |
| `modbus_slave`                  | `binary_sensor` of the communication of the unit                  |

- The entities of a Modbus unit or of a 1-Wire bus are one device of Home Assistant, e.g. `evok xS51`.
  The name of an entity is the alias of the device, e.g. `pump`, or its type and circuit, e.g. `RO 1_01`.
- The configs are published retained to `<ha_prefix>/<component>/<node>/<object_id>/config`
  (`ha_prefix` is `homeassistant` by default, the node is the prefix of Evok with the characters other than letters, digits, `_` and `-` replaced by `_`,
  e.g. `evok` or `evok_boiler-room`) before the first state
  of each device, again when they change (an alias, the mode of an AO) and after each connection to the broker.
- The entities are available while the status of Evok is `online` and the communication of their device
  is `ok` (`comm` of its state), an entity of a Modbus unit which does not respond is unavailable.
- The switches and the numbers send the commands to `<prefix>/<device>/<circuit>/set`. A pulse
  is set by the sequencer, e.g. by an MQTT action of an automation to `<prefix>/sequencer/ro_1_01/set`.
- `device_mask` limits the announced devices too.

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
