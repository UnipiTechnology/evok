# Evok APIs

For more information see our [API documentation](https://unipitechnology.stoplight.io/docs/evok/).

Evok APIs are listening on IP `127.0.0.1` and port `8080` by default. You can change this behavior in [configuration](./configs/evok_configuration.md).
With a `token` in the configuration all APIs require it, see [Security](./security.md).

**Comparison table:**

| API                         | multiple commands per request | Recommended usage    | Communication  |
|-----------------------------|-------------------------------|----------------------|----------------|
| [REST](#rest-doc)           | ❌                             | By hand              | client to Evok |
| [JSON](#json-doc)           | ❌                             | Automated            | client to Evok |
| [WebSocket](#websocket-doc) | ❌                             | Real-time automated  | both ways      |
| [BULK](#bulk-doc)           | ✅                             | Automated            | client to Evok |
| [Webhook](#webhook-doc)     | N/A                           | Listening to changes | Evok to client |
| [RPC](#rpc-doc)             | ✅ (batch)                     | Automated            | client to Evok |
| [MQTT](#mqtt-doc)           | ❌                             | Integration by a broker | both ways   |

## REST ([doc](./apis/rest.md))

The REST API provides a simple interface for sending and receiving data in a stateless, cacheable communications.

## JSON ([doc](./apis/json.md))

Similar to the REST API, but in JSON format.

## WebSocket ([doc](./apis/websocket.md))

The WebSocket API allows for two-way communication between the client and the server over an open connection. Evok sends changes to every connected client. A list of reflected devices can be defined. It is suitable if you need to immediately react to events in your application.

## BULK ([doc](./apis/bulk.md))

The BULK API is designed to provide an efficient way for clients to update, create or delete large amounts of data.

## Webhook ([doc](./apis/webhook.md))

The Webhook API provides a mechanism for pushing real-time updates to clients. Evok sends the changes to the specified hostname and port. A list of reflected devices can be defined. It is suitable for collecting real-time information about the application.

## Sequencer ([doc](./apis/sequencer.md))

The pulses and the sequences of the outputs (RO, DO, LED) are set by the sequencer of each output, a device of the type `sequencer` of the other APIs, e.g. `POST /rest/sequencer/do_1_01` with `value=1&pulse_duration=2`.

## RPC ([doc](./apis/rpc.md))

The RPC (Remote Procedure Call) API is used for invoking procedures, functions or methods across a network.

## MQTT ([doc](./apis/mqtt.md))

The MQTT API publishes the states of the devices to an MQTT broker and receives the commands from it. The states are retained, a new client gets the actual state of all devices at once. It is suitable for an integration by a broker, e.g. Home Assistant or Node-RED. Its access is controlled by the broker, not by the `token`.
