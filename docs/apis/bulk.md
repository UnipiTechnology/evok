# Evok Bulk API

The Bulk API is designed to provide an efficient way for clients to update, create or delete large amounts of data. This protocol supports multiple writes in one request, but it is suitable for automated requests thanks JSON protocol, which is easily machine-processed.

## Request

The request is a JSON object sent by POST to `/bulk`, with any of these parts:

```json
{
  "group_queries": [
    {"device_types": ["di", "do"], "group": 1, "device_circuits": ["1_01", "my_alias"]}
  ],
  "group_assignments": [
    {"device_type": "do", "group": 2, "device_circuits": ["2_01"], "assigned_values": {"value": 0}}
  ],
  "individual_assignments": [
    {"device_type": "do", "device_circuit": "1_01", "assigned_values": {"value": 1}}
  ]
}
```

- `group_queries` - returns the states of all devices of the `device_types`
- `group_assignments` - sets the `assigned_values` to all devices of the `device_type`
- `individual_assignments` - sets the `assigned_values` to the device of the `device_type` and `device_circuit`
  (a circuit or an alias)

The devices of a group can be limited by optional parameters:

- `group` - the major group of the devices, e.g. the section of a Modbus unit
- `device_circuits` - a list of circuits or aliases

The `assigned_values` are the same params as in [REST](rest.md) and they are validated in the same way.
Altnames of the device types such as `input` or `relay` can be used.

## Response

The response contains `"success": true` and a list of results for every part of the request, in the order
of the commands: a list of states for every group query and group assignment and a state for every individual
assignment. The body of a request can have at most 1 MB.

The queries are processed first, so they return the states before the assignments.
The assignments (`group_assignments` and `individual_assignments` together) are done by the Modbus units:
the devices of a unit are set together, in the order of the request, then the unit is read once
and the states of its devices are returned as they are after the writes. The units are set one after another,
in the order of their first assignment; a device which is not on a Modbus unit (e.g. a 1-Wire sensor)
is set as a unit of its own. The results are in the order of the request.

## Errors

All assignments are checked before any device is set. An unknown device type, circuit or alias is reported
with the status 404, invalid params with the status 400, and no device is set.

An error while setting a device is reported with the status 400 (e.g. a value out of range), 503
(a Modbus unit which failed its last scan, none of its devices is set, or a failed request of a change
of the unit) or 500. The response contains the results
of the units set before the error and of the assignments of its unit done before it, the following units are not set.

```json
{"success": false, "errors": {"ValueError": "Value out of range"},
 "individual_assignments": [{"dev": "do", "circuit": "1_01", "value": 1}]}
```

## Examples

For python examples you need installed `requests` package. You can install it with this command: `pip3 install requests`.

### Setting DOs to HIGH

DO 1.01, 1.02, 1.03, 1.04 will be set to HIGH.

```python title="Python"
import requests

payload = {"individual_assignments": []}

for circuit in ['1_01', '1_02', '1_03', '1_04']:
    cmd = {"device_type": "do", "device_circuit": circuit, "assigned_values": {'value': 1}}
    payload['individual_assignments'].append(cmd)

url = 'http://127.0.0.1:8080/bulk'
print(requests.post(url, json=payload).json())
```

```rs title="Output"
{'individual_assignments': [{'dev': 'do', 'circuit': '1_01', 'value': 0, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_02', 'value': 0, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_03', 'value': 0, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_04', 'value': 0, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}]}
```

### Setting DOs to LOW

DO 1.01, 1.02, 1.03, 1.04 will be set to LOW.

```python title="Python"
import requests

payload = {"individual_assignments": []}

for circuit in ['1_01', '1_02', '1_03', '1_04']:
    cmd = {"device_type": "do", "device_circuit": circuit, "assigned_values": {'value': 0}}
    payload['individual_assignments'].append(cmd)

url = 'http://127.0.0.1:8080/bulk'
print(requests.post(url, json=payload).json())
```

``` rs title="Output"
{'individual_assignments': [{'dev': 'do', 'circuit': '1_01', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_02', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_03', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}, {'dev': 'do', 'circuit': '1_04', 'value': 1, 'pending': False, 'mode': 'Simple', 'modes': ['Simple', 'PWM'], 'pwm_freq': 4800.0, 'pwm_duty': 0}]}
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)