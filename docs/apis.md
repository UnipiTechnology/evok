# Evok APIs

For more information see our [API documentation](https://unipitechnology.stoplight.io/docs/evok/).

Evok APIs are listening on IP `127.0.0.1` and port `8080` by default. You can change this behavior in [configuration](./configs/evok_configuration.md).

**Comparison table:**

| API                         | multiple commands per request | Recommended usage    | Communication  |
|-----------------------------|-------------------------------|----------------------|----------------|
| [REST](#rest-doc)           | ❌                             | By hand              | client to Evok |
| [JSON](#json-doc)           | ❌                             | Automated            | client to Evok |
| [WebSocket](#websocket-doc) | ❌                             | Real-time automated  | both ways      |
| [BULK](#bulk-doc)           | ✅                             | Automated            | client to Evok |
| [Webhook](#webhook-doc)     | N/A                           | Listening to changes | Evok to client |
| [RPC](#rpc-doc)             | ❌                             | Automated            | client to Evok |

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

## RPC ([doc](./apis/rpc.md))

The RPC (Remote Procedure Call) API is used for invoking procedures, functions or methods across a network.
