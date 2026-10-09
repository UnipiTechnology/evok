# Security

The APIs of Evok can read and set all inputs and outputs of the controller. By default they listen only on
the local interface `127.0.0.1`, the applications on the controller (e.g. Node-RED) use them without
authentication, the other devices of the network cannot connect to them.

## Access from the network

To use the APIs from the network, set the [address](configs/evok_configuration.md#api-settings) of the interface
and a `token`, without it anybody in the network controls the IOs:

```yaml
apis:
  address:                  # all interfaces
  token: 3f8c...e21a        # e.g. made by: openssl rand -hex 32
```

Keep the token secret, it gives the full access to the APIs, and restrict the access to `config.yaml`
(e.g. `chmod 600 /etc/evok/config.yaml`).

### Sending the token

All APIs require the token except `/version` and the preflight `OPTIONS` of a browser. A request without
the token gets the status `401`.

| Client                          | How                                                                       |
|---------------------------------|---------------------------------------------------------------------------|
| REST, JSON, Bulk, RPC           | header `Authorization: Bearer <token>`                                    |
| clients with Basic auth only    | Basic authentication with any user name and the token as the password     |
| WebSocket                       | the header as above, or `ws://<host>:8080/ws?token=<token>` from a browser |

The token in the URL is accepted only by the WebSocket, a browser cannot set a header of a WebSocket.
The other APIs refuse it, the URL is kept in the logs of proxies and in the history of browsers.

```bash
curl -H "Authorization: Bearer <token>" http://192.168.1.10:8080/rest/all
curl -u any:<token> http://192.168.1.10:8080/rest/all
```

```python
import requests

headers = {"Authorization": "Bearer <token>"}
print(requests.get("http://192.168.1.10:8080/json/do/1_01", headers=headers).json())
```

## Web applications

A web page on another address than the API (e.g. a dashboard served by Node-RED on port 1880) cannot use
the API from a browser by default, Evok sends no CORS headers and refuses its WebSocket by `403`.
This protects the IOs from every other web page opened in a browser in your network. Add the origins
of your applications to `allowed_origins`:

```yaml
apis:
  allowed_origins: ["http://192.168.1.10:1880"]
```

A WebSocket from a client which is not a browser (Node-RED nodes, Python) sends no origin, it is not checked.

### Behind a reverse proxy

A WebSocket from a browser through a reverse proxy, e.g. nginx, is accepted when the proxy passes the host
of the request, otherwise the origin of the page does not match the host and the connection is refused:

```nginx
location /ws {
    proxy_pass http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

## Encryption

Evok does not encrypt the communication, the token is sent as plain text. Outside of a trusted network use
a reverse proxy with TLS, e.g. nginx with a certificate, in front of Evok listening on `127.0.0.1`.
