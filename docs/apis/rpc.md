# Evok RPC API

The RPC (Remote Procedure Call) API is used for invoking procedures, functions or methods across a network. It is suitable for automated request.

The API uses [JSON-RPC](https://www.jsonrpc.org/specification) at `/rpc`. Params can be passed as an array in the order
of the table below or as an object with their names.

## Methods

| Method                | Params                               | Result                                                                |
|-----------------------|--------------------------------------|-----------------------------------------------------------------------|
| `input_get`           | `circuit`                            | `[value, debounce]` of a DI                                           |
| `input_get_value`     | `circuit`                            | value of a DI                                                         |
| `input_set`           | `circuit`, `debounce`                | state of the DI                                                       |
| `relay_get`           | `circuit`                            | value of a relay output (RO)                                          |
| `relay_set`           | `circuit`, `value`                   | the value set, `0` or `1`                                             |
| `relay_set_for_time`  | `circuit`, `value`, `pulse_duration` | state of the RO, the value is inverted after `pulse_duration` seconds |
| `output_get`          | `circuit`                            | `[value, pending]` of a DO, `pending` is true during a pulse          |
| `output_set`          | `circuit`, `value`                   | the value set, `0` or `1`                                             |
| `output_set_for_time` | `circuit`, `value`, `pulse_duration` | state of the DO, the value is inverted after `pulse_duration` seconds |
| `ai_get`              | `circuit`                            | state of an AI                                                        |
| `ao_set_value`        | `circuit`, `value`                   | the value written to an AO                                            |
| `ao_set`              | `circuit`, `value`, `mode`           | state of the AO                                                       |
| `owbus_get`           | `circuit`                            | scan interval of a 1-Wire bus                                         |
| `owbus_set`           | `circuit`, `scan_interval`           | state of the 1-Wire bus                                               |
| `owbus_scan`          | `circuit`                            | state of the 1-Wire bus, the scan is started                          |
| `owbus_list`          | `circuit`                            | addresses of the sensors on the 1-Wire bus by their type              |
| `sensor_get`          | `circuit`                            | `[value, lost, readtime, interval]` of a 1-Wire sensor                |
| `sensor_get_value`    | `circuit`                            | value of a 1-Wire sensor                                              |
| `sensor_set`          | `circuit`, `interval`                | state of the 1-Wire sensor                                            |

A value of an output is converted to an integer, so `'0'` switches the output off. The `circuit` can be also an alias.
The param `timeout` of `output_set_for_time` is a deprecated alias of `pulse_duration`.

## Errors

| Code     | Meaning                                                                                    |
|----------|--------------------------------------------------------------------------------------------|
| `-32601` | Unknown method                                                                             |
| `-32602` | Invalid params: a missing or unknown param, an invalid value, an unknown circuit or alias |
| `-32603` | Internal error                                                                             |

```rs title="Example"
{'jsonrpc': '2.0', 'id': 0, 'error': {'code': -32602, 'message': "Invalid params: Circuit or alias with name '9_99' not defined!"}}
```

## Examples

For python examples you need installed `requests` package. You can install it with this command: `pip3 install requests`.

### Reading DI

Value of DI 1.01 will be returned.

```python  title="Python"
import requests

payload = {
    "method": "input_get",
    "params": ["1_01"],
    "jsonrpc": "2.0",
    "id": 0,
}

url = 'http://127.0.0.1:8080/rpc'
response = requests.post(url, json=payload).json()
print(response)
```

```rs title="Output"
{'jsonrpc': '2.0', 'id': 0, 'result': [0, 50]}
```

### Setting DO

DO 1.01 will be set to HIGH.

```python  title="Python"
import requests

payload = {
    "method": "output_set",
    "params": ["1_01", '1'],
    "jsonrpc": "2.0",
    "id": 0,
}

url = 'http://127.0.0.1:8080/rpc'
response = requests.post(url, json=payload).json()
print(response)
```

```rs title="Output"
{'jsonrpc': '2.0', 'id': 0, 'result': 1}
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
