# Evok Webhook API

The Webhook API provides a mechanism for pushing real-time updates to clients. Evok sends the changes to the specified hostname and port. A list of reflected devices can be defined. It is suitable for collecting information about the running application.

## Examples

For python examples you need installed `flask` package. You can install it with this command: `pip3 install flask`.

### Creating simple Webhook server

```python title="Python"
from flask import Flask, request
import json

app = Flask(__name__)

@app.route('/', methods=['POST', 'GET'])
def respond():
    print(dict(request.values))
    return json.dumps({"status": "success"}), 200


if __name__=="__main__":
    app.run(host='127.0.0.1', port=8181)
```

This code starts simple webhook server on localhost on port 8181. You can configure Evok for sending events on this server.

Evok configuration:

For more information see [Evok configuration](../configs/evok_configuration.md).

```yaml
  webhook:
    enabled: true
    address: http://127.0.0.1:8181
    device_mask: ["do", "ro", "ao"]
    complex_events: true
```

!!! note

    After you change configuration, you have to restart the Evok with the command `systemctl restart evok`.

```bash title="Output"
 * Serving Flask app 'server'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on http://127.0.0.1:8181
Press CTRL+C to quit
{'[{"dev": "do", "circuit": "1_03", "value": 0, "pending": false, "mode": "Simple", "modes": ["Simple", "PWM"], "glob_dev_id": 2, "pwm_freq": 4800.0, "pwm_duty": 0}]': ''}
127.0.0.1 - - [12/Feb/2024 13:54:58] "POST / HTTP/1.1" 200 -
{'[{"dev": "ro", "circuit": "2_04", "value": 1, "pending": false, "mode": "Simple", "modes": ["Simple"], "glob_dev_id": 3}]': ''}
127.0.0.1 - - [12/Feb/2024 13:55:02] "POST / HTTP/1.1" 200 -
{'[{"dev": "ro", "circuit": "2_04", "value": 0, "pending": false, "mode": "Simple", "modes": ["Simple"], "glob_dev_id": 3}]': ''}
127.0.0.1 - - [12/Feb/2024 13:55:02] "POST / HTTP/1.1" 200 -
{'[{"dev": "ao", "circuit": "1_01", "mode": "Voltage", "modes": {"Voltage": {"value": 0, "unit": "V", "range": [0, 10]}, "Current": {"value": 1, "unit": "mA", "range": [0, 20]}, "Resistance": {"value": 2, "unit": "Ohm", "range": [0, 2000]}}, "glob_dev_id": 2, "unit": "V", "value": 8.301}]': ''}
127.0.0.1 - - [12/Feb/2024 13:55:05] "POST / HTTP/1.1" 200 -
{'[{"dev": "ao", "circuit": "2_01", "mode": "Voltage", "modes": {"Voltage": {"unit": "V", "range": [0, 10]}}, "glob_dev_id": 3, "value": 1.5, "unit": "V", "range": [0, 10]}]': ''}
127.0.0.1 - - [12/Feb/2024 13:55:05] "POST / HTTP/1.1" 200 -
{'[{"dev": "ao", "circuit": "1_01", "mode": "Voltage", "modes": {"Voltage": {"value": 0, "unit": "V", "range": [0, 10]}, "Current": {"value": 1, "unit": "mA", "range": [0, 20]}, "Resistance": {"value": 2, "unit": "Ohm", "range": [0, 2000]}}, "glob_dev_id": 2, "unit": "V", "value": 2.7}]': ''}
127.0.0.1 - - [12/Feb/2024 13:55:06] "POST / HTTP/1.1" 200 -
...
```

!!! tip
    You can learn more about the circuit parameter [here](../circuit.md)
