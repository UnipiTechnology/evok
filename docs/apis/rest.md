# Evok REST API

The REST API provides a simple interface for sending and receiving data in a stateless, cacheable communications. This protocol does not support multiple writes in one request, thus it is suitable mainly for hand-made requests.

## Routes

`<fmt>` is `rest` or `json`, both return JSON. The POST of `rest` takes the params as a form or as a JSON object (with `Content-Type: application/json`
or a body starting with `{`), of `json` as a JSON object.

| Route                                  | Reply                                                                         |
|----------------------------------------|-------------------------------------------------------------------------------|
| `GET /<fmt>/<dev>/<circuit>`           | the state of the device                                                       |
| `GET /<fmt>/<dev>/<circuit>/<prop>`    | `{"<prop>": <value>}`, an unknown property is `404`                           |
| `GET /<fmt>/<dev>/all`                 | the list of the states of all devices of the type                             |
| `GET /<fmt>/<dev>/all/<prop>`          | the list of `{"circuit": ..., "<prop>": ...}`, the devices without the property are skipped |
| `POST /<fmt>/<dev>/<circuit>`          | sets the params in the body, `{"success": true, "result": <state>}`           |
| `POST /<fmt>/<dev>/<circuit>/alias`    | the same, e.g. with the body `alias=pump`; another last part of the URL is `404` |
| `POST /<fmt>/<dev>/all`                | `404`, several devices are set by the [bulk](bulk.md) API                     |
| `GET /<fmt>/all`                       | the states of all devices except the sequencers, the Modbus buses (`serial_bus`, `tcp_bus`) and `run`; `POST` is `405` |
| `GET /version`                         | the version of Evok as text, e.g. `v3.1.0`, without the token                 |
| `GET /log?lines=N`                     | the last `N` lines of the log file as text (255 by default, at most 1000), `404` without a `file` in [logging](../configs/evok_configuration.md#logging) |

The `circuit` can be also an alias. A pulse of an output is set by its [sequencer](sequencer.md).

## Replies and errors

A POST returns the state of the device after the change:

```json
{"success": true, "result": {"dev": "do", "circuit": "1_01", "value": 1, ...}}
```

The params of a POST are validated by the JSON schema of the device type, an unknown param is refused.
An error returns the type of the error and its message:

```json
{"success": false, "errors": {"DeviceNotFound": "Circuit or alias '9_99' with devtype 'do' not found"}}
```

| Status | Error                                                                                               |
|--------|-----------------------------------------------------------------------------------------------------|
| `400`  | invalid params or data (`ValueError`, `ValidationError`)                                            |
| `401`  | a missing or invalid token, see [Security](../security.md)                                          |
| `403`  | a change with the `read_token` (`ReadOnlyAccess`)                                                   |
| `404`  | an unknown device type, circuit, alias or property (`DeviceNotFound`)                               |
| `409`  | a change of an output while its sequencer runs (`SequenceRunning`)                                  |
| `503`  | the Modbus unit failed its last scan (`UnitUnavailable`) or the request of the change failed (`UnitCommunicationError`) |
| `500`  | an internal error, `{"Server error": "internal"}`, the details are in the log                       |

## Examples

For python examples you need installed `requests` package. You can install it with this command: `pip3 install requests`.

### Reading DI

Value of DI 1.01 will be returned.

=== "Python"

    ```python
    import requests

    def get_request(host: str, port: str, dev_type: str, circuit: str):
        url = f"http://{host}:{port}/rest/{dev_type}/{circuit}"
        return requests.get(url=url)

    if __name__ == '__main__':
        ret = get_request(host='127.0.0.1', port='8080', dev_type='di', circuit='1_01')
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request GET --url 'http://127.0.0.1:8080/rest/di/1_01/'
    ```

```rs title="Output"
{"dev": "di", "circuit": "1_01", "value": 0, "debounce": 50, "counter_modes": ["Enabled", "Disabled"], "counter_mode": "Enabled", "counter": 0, "mode": "Simple", "modes": ["Simple", "DirectSwitch"], "comm": "ok", "last_comm": 0.041}
```

### Setting DO

DO 1.01 will be set to HIGH.

=== "Python"

    ```python
    import requests

    def send_request(host: str, port: str, dev_type: str, circuit: str, value: bool):
        url = f"http://{host}:{port}/rest/{dev_type}/{circuit}"
        data = {'value': str(int(value))}
        return requests.post(url=url, data=data)

    if __name__ == '__main__':
        ret = send_request(host='127.0.0.1', port='8080', dev_type='do', circuit='1_01', value=True)
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request POST --url 'http://127.0.0.1:8080/rest/do/1_01/' --data 'value=1'
    ```

```rs title="Output"
{"success": true, "result": {"dev": "do", "circuit": "1_01", "value": 1, "mode": "Simple", "modes": ["Simple", "PWM"], "pwm_freq": 4800.0, "pwm_duty": 0, "comm": "ok", "last_comm": 0.041}}
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
