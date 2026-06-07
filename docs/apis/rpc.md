# Evok RPC API

The RPC (Remote Procedure Call) API is used for invoking procedures, functions or methods across a network. It is suitable for automated request.

## Examples

For python examples you need installed `requests` package. You can install it with this command: `pip3 install requests`.

### Reading DI

Value of DI 1.01 will be returned.

```python  title="Python"
import requests

payload = {
    "method": "di_get",
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
    "method": "do_set",
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
