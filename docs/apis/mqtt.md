# Evok MQTT API

The MQTT API provides two-way communication between Evok and any MQTT broker. Evok
publishes device state changes as events and subscribes to a command topic so external
clients can read or control devices.

It is suitable for IoT integrations, home-automation platforms (Home Assistant, Node-RED,
OpenHAB), and any system that already runs an MQTT broker.

## Topic structure

All topics are prefixed with the `client-id` configured in `/etc/evok/config.yaml`.

| Direction | Topic pattern | Payload |
|-----------|--------------|---------|
| Evok → client (event) | `<client-id>/event/<devtype>/<circuit>` | JSON object — full device state |
| Client → Evok (command) | `<client-id>/cmd/<devtype>/<circuit>` | JSON object — fields to set |
| Client → Evok (query all) | `<client-id>/cmd/ALL` | `{}` |
| Evok → client (query response) | `<client-id>/cmd/ALL` | JSON array — all device states |

**Examples** (client-id = `evok`):

```
evok/event/di/1_01          ← Evok publishes when DI 1_01 changes
evok/event/ro/2_04          ← Evok publishes when relay 2_04 changes
evok/cmd/ro/2_04            → client sends {"value": 1} to switch relay ON
evok/cmd/ALL                → client sends {} to request all device states
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)

## Commands

### Set a device value

Publish a JSON object to `<client-id>/cmd/<devtype>/<circuit>`.
Evok validates the payload against the device schema, applies the change, and publishes
a confirmation event on the corresponding `event/` topic.

```bash title="mosquitto_pub — switch relay ON"
mosquitto_pub -h localhost -u evok -P secret \
  -t evok/cmd/ro/1_01 -m '{"value": 1}'
```

```bash title="mosquitto_pub — switch relay OFF"
mosquitto_pub -h localhost -u evok -P secret \
  -t evok/cmd/ro/1_01 -m '{"value": 0}'
```

```bash title="mosquitto_pub — set analog output to 5 V"
mosquitto_pub -h localhost -u evok -P secret \
  -t evok/cmd/ao/1_01 -m '{"value": 5.0, "mode": "Voltage"}'
```

### Query all devices

Publish any message to `<client-id>/cmd/ALL` (case-insensitive). Evok replies on the
same topic with a JSON array containing the full state of every registered device.

```bash title="mosquitto_pub — request all device states"
mosquitto_pub -h localhost -u evok -P secret \
  -t evok/cmd/ALL -m '{}'
```

```bash title="mosquitto_sub — subscribe and see the response"
mosquitto_sub -h localhost -u evok -P secret \
  -t evok/cmd/ALL -C 2
```

## Listening for events

Subscribe to `<client-id>/event/#` to receive all device state change notifications.

```bash title="mosquitto_sub — listen for all events"
mosquitto_sub -h localhost -u evok -P secret \
  -t evok/event/# -v
```

```text title="Output"
evok/event/di/1_01 {"dev": "di", "circuit": "1_01", "value": 1, ...}
evok/event/ro/2_04 {"dev": "ro", "circuit": "2_04", "value": 0, ...}
```

## Configuration

Add an `mqtt` section inside `apis` in `/etc/evok/config.yaml`:

```yaml
apis:
  mqtt:
    enabled: true
    address: localhost      # MQTT broker hostname or IP
    port: 1883
    client-id: evok         # unique identifier for this Evok instance
    username: evok          # optional — omit or leave blank if broker has no auth
    password: secret        # optional
    keepalive: 60
    qos: 0
```

For full configuration reference see [Evok configuration](../configs/evok_configuration.md#mqtt).

!!! note
    After changing configuration, restart Evok: `systemctl restart evok`

## Python examples

The examples below use `aiomqtt` (`pip install aiomqtt`).

### Reading — subscribe to all device events

```python title="Python — listen for events"
import asyncio, json
import aiomqtt

BROKER   = "192.168.1.100"
USER     = "evok"
PASSWORD = "secret"
ID       = "evok"


async def main():
    async with aiomqtt.Client(
        hostname=BROKER, username=USER, password=PASSWORD,
        identifier="my-listener",
    ) as client:
        # Subscribe to every device event
        await client.subscribe(f"{ID}/event/#")

        print("Listening for events (Ctrl-C to stop)…")
        async for msg in client.messages:
            topic   = str(msg.topic)
            payload = json.loads(msg.payload)
            devtype = topic.split("/")[2]   # e.g. "di", "ro", "ao"
            circuit = topic.split("/")[3]   # e.g. "1_01"
            print(f"{devtype}/{circuit}: value={payload.get('value')}")


asyncio.run(main())
```

```text title="Output"
Listening for events (Ctrl-C to stop)…
di/1_01: value=0
di/1_02: value=1
ro/2_04: value=0
ao/1_01: value=5.0
```

### Writing — set a device value and confirm the event

```python title="Python — set DO 1_01 ON, wait for confirmation event"
import asyncio, json
import aiomqtt

BROKER   = "192.168.1.100"
USER     = "evok"
PASSWORD = "secret"
ID       = "evok"
CIRCUIT  = "do/1_01"


async def main():
    async with aiomqtt.Client(
        hostname=BROKER, username=USER, password=PASSWORD,
        identifier="my-writer",
    ) as client:
        event_topic = f"{ID}/event/{CIRCUIT}"
        await client.subscribe(event_topic)

        # Send the set command
        await client.publish(f"{ID}/cmd/{CIRCUIT}", json.dumps({"value": 1}))
        print(f"Sent: set {CIRCUIT} = 1")

        # Wait for Evok's confirmation event
        async for msg in client.messages:
            if str(msg.topic) == event_topic:
                state = json.loads(msg.payload)
                print(f"Confirmed: {CIRCUIT} value={state['value']}")
                break


asyncio.run(main())
```

```text title="Output"
Sent: set do/1_01 = 1
Confirmed: do/1_01 value=1
```

### Reading — query all devices at once

```python title="Python — request full device list via ALL command"
import asyncio, json
import aiomqtt

BROKER   = "192.168.1.100"
USER     = "evok"
PASSWORD = "secret"
ID       = "evok"


async def main():
    async with aiomqtt.Client(
        hostname=BROKER, username=USER, password=PASSWORD,
        identifier="my-query",
    ) as client:
        all_topic = f"{ID}/cmd/ALL"
        await client.subscribe(all_topic)

        await client.publish(all_topic, json.dumps({}))

        async for msg in client.messages:
            payload = json.loads(msg.payload)
            if isinstance(payload, list):          # skip echo of our own {}
                for device in payload:
                    print(f"{device['dev']:6} {device['circuit']:8} value={device.get('value')}")
                break


asyncio.run(main())
```

```text title="Output"
di     1_01     value=0
di     1_02     value=1
do     1_01     value=0
do     1_02     value=0
ai     1_01     value=8.7
ao     1_01     value=5.0
```

## End-to-end test script

`examples/test_mqtt.py` in the Evok repository is a ready-made E2E test that verifies
the full MQTT datapath against a live unit:

```bash
python examples/test_mqtt.py \
    --broker 192.168.1.100 \
    --client-id evok \
    --circuit do/1_01 \
    --username evok \
    --password secret
```

It runs six automated checks: ALL query, set ON/OFF round-trips, state consistency,
and both error paths (invalid payload, unknown circuit).
