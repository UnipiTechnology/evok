# Evok JSON API

The JSON API provides a simple interface for sending and receiving data in a stateless, cacheable communications. This protocol does not support multiple writes in one request, but it is suitable for automated requests thanks to JSON protocol, which is easily machine-processed.

## Examples

For python examples you need installed `requests` package. You can install it with this command: `pip3 install requests`.

### Reading DI

Value of DI 1.01 will be returned.

=== "Python"

    ```python
    import requests

    def get_request(host: str, port: str, dev_type: str, circuit: str):
        url = f"http://{host}:{port}/json/{dev_type}/{circuit}"
        return requests.get(url=url)

    if __name__ == '__main__':
        ret = get_request(host='127.0.0.1', port='8080', dev_type='di', circuit='1_01')
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request GET --url 'http://127.0.0.1:8080/json/di/1_01/'
    ```

```rs title="Output"
{"dev": "di", "circuit": "1_01", "value": 0, "debounce": 50, "counter_modes": ["Enabled", "Disabled"], "counter_mode": "Enabled", "counter": 0, "mode": "Simple", "modes": ["Simple", "DirectSwitch"], "glob_dev_id": 2}
```

### Setting DO

DO 1.01 will be set to HIGH.

=== "Python"

    ```python
    import requests, json

    def send_request(host: str, port: str, dev_type: str, circuit: str, value: bool):
        url = f"http://{host}:{port}/json/{dev_type}/{circuit}"
        data = {'value': str(int(value))}
        return requests.post(url=url, data=json.dumps(data))

    if __name__ == '__main__':
        ret = send_request(host='127.0.0.1', port='8080', dev_type='do', circuit='1_01', value=True)
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request POST --url 'http://127.0.0.1:8080/json/do/1_01/' --data '{"value": 1}'
    ```

```rs title="Output"
{'success': True, 'result': {'dev': 'do', 'circuit': '1_01', 'value': 0, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'glob_dev_id': 2, 'pwm_freq': 4800.0, 'pwm_duty': 0}}
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
