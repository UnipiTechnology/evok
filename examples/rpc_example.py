"""JSON-RPC API: read the devices, also by a batch request, see docs/apis/rpc.md"""

import os

import requests

HOST = os.environ.get("EVOK_HOST", "127.0.0.1")
PORT = os.environ.get("EVOK_PORT", "8080")
TOKEN = os.environ.get("EVOK_TOKEN")  # the token of 'apis' in the configuration, if it is set
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def call(method: str, *params, call_id: int = 0) -> dict:
    return {"jsonrpc": "2.0", "method": method, "params": list(params), "id": call_id}


def rpc(request):
    return requests.post(f"http://{HOST}:{PORT}/rpc", json=request, headers=HEADERS, timeout=5).json()


def main():
    # [value, debounce] of a digital input
    print(rpc(call("input_get", "1_01")))
    # a batch: a list of calls returns a list of the results
    print(rpc([call("input_get_value", "1_01", call_id=1), call("output_get", "1_01", call_id=2)]))


if __name__ == "__main__":
    main()
