# Evok aliases

It is possible to set aliases to devices, so they have more describing permanent names.

There are several restrictions to aliases:

- Every alias needs to be globally unique, not just within its own class.
- Aliases can only contain alphanumeric characters, underscores and dashes. This is to allow devices to address via the alias using the APIs (i.e. setting an alias for a `relay 1_01` to `bedroom_light` will allow it to be addressed both as `/rest/relay/al_bedroom_light` as well as `/rest/relay/1_01`)
- Invalid aliases will be rejected by the API, with the previous alias remaining.

!!! warning

    The set aliases are initially stored only in the RAM, after 5 minutes they will be permanently saved to flash. Saving of all set aliases can be done by calling `/run/alias`.

Aliases can be set in a total of 3 ways:

- Using the API
- Using the [evok-web](https://github.com/UniPiTechnology/evok-web-jq)
- Manually writing to the configuration file

## Examples

For python examples you need to have installed `requests` package. You can install it with command `pip3 install requests`.

### Setting alias for DO

DO 1_01 will be called my_relay.

=== "Python"

    ```python
    import requests

    def set_alias(host: str, port: str, dev_type: str, circuit: str, value: str):
        url = f"http://{host}:{port}/rest/{dev_type}/{circuit}"
        data = {'alias': str(value)}
        return requests.post(url=url, data=data)

    if __name__ == '__main__':
        ret = set_alias(host='127.0.0.1', port='8080', dev_type='relay', circuit='1_01', value='my_relay')
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request POST --url 'http://127.0.0.1:8080/rest/relay/1_01/' --data 'alias=my_relay'
    ```

```rs title="Output"
{'success': True, 'result': {'dev': 'relay', 'relay_type': 'digital', 'circuit': '1_01', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'glob_dev_id': 2, 'pwm_freq': 4800.0, 'pwm_duty': 0, 'alias': 'my_relay'}}
```

### Removing alias for DO

Alias of DO 1_01 will be removed.

=== "Python"

    ```python
    import requests

    def set_alias(host: str, port: str, dev_type: str, circuit: str, value: str):
        url = f"http://{host}:{port}/rest/{dev_type}/{circuit}"
        data = {'alias': str(value)}
        return requests.post(url=url, data=data)

    if __name__ == '__main__':
        ret = set_alias(host='127.0.0.1', port='8080', dev_type='relay', circuit='1_01', value='')
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request POST --url 'http://127.0.0.1:8080/rest/relay/1_01/' --data 'alias='
    ```

```rs title="Output"
{'success': True, 'result': {'dev': 'relay', 'relay_type': 'digital', 'circuit': '1_01', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'glob_dev_id': 2, 'pwm_freq': 4800.0, 'pwm_duty': 0}}
```

### Force saving alias to flash

=== "Python"

    ```python
    import requests

    def save_aliases(host: str, port: str, value: bool):
        url = f"http://{host}:{port}/rest/run/alias"
        data = {'save': int(value)}
        return requests.post(url=url, data=data)

    if __name__ == '__main__':
        ret = save_aliases(host='127.0.0.1', port='8080', value=True)
        print(ret.json())
    ```

=== "curl"

    ```bash
    curl --request POST --url 'http://127.0.0.1:8080/rest/run/alias/' --data 'save=1'
    ```

```rs title="Output"
{'success': True, 'result': {'dev': 'run', 'circuit': 'alias', 'save': False, 'aliases': {'my_relay': 'relay_1_01'}}}
```

## Setting aliases manually

You can set aliases manually in the alias config file. This option is especially suitable for transferring an alias from another device.

The configuration file is located in `/var/lib/evok/aliases.yaml`. First required parameter is `version`, it affects the configuration file structure. Second parameter is list of aliases names `aliases`, each element in this list must contain 'circuit' and 'devtype' specifying the aliased device. Both of these parameters are available using the API.

```yaml title="Example"
version: 2.0
aliases:
  my_input:
    circuit: '1_01'
    devtype: 2
  my_relay:
    circuit: '1_01'
    devtype: 0
```


!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
