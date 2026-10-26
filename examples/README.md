# Examples

Clients of the APIs of Evok in Python. The address of Evok is given by the environment variables
`EVOK_HOST` (default `127.0.0.1`) and `EVOK_PORT` (default `8080`), the token by `EVOK_TOKEN`
when it is set in the configuration:

```bash
EVOK_HOST=192.168.1.2 EVOK_TOKEN=<token> python rest_example.py
```

Evok listens on `127.0.0.1` by default, set `address` in `apis` of the configuration to reach it
from another computer, see [the configuration](../docs/configs/evok_configuration.md).
The examples which change a device switch the user LEDs `1_01`..`1_04`.

| Example | API | Python packages |
|---------|-----|-----------------|
| `rest_example.py` | [REST](../docs/apis/rest.md): read a device, set a LED by a form | `requests` |
| `json_example.py` | [JSON](../docs/apis/json.md): read a device, set a LED by a JSON body | `requests` |
| `bulk_example.py` | [Bulk](../docs/apis/bulk.md): a query and the assignments in one request | `requests` |
| `rpc_example.py` | [JSON-RPC](../docs/apis/rpc.md): a call and a batch | `requests` |
| `websocket_example.py` | [WebSocket](../docs/apis/websocket.md): the filter, the events, a change | `websocket-client` |
| `webhook_example.py` | [Webhook](../docs/apis/webhook.md): a receiver of the changes on port 8181 | `flask` |
| `benchmark.py` | the response times of REST and JSON, the reads and the writes of a LED | `aiohttp` |
| `config.yaml` | the commented template of the configuration | |

```bash
pip install requests websocket-client flask aiohttp
```
