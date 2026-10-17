"""JSON-RPC 2.0 client of the Evok ``/rpc`` endpoint."""

from typing import Any

from .http import HttpClient

_jsonrpc_id: int = 0


class RpcClient:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def call(self, method: str, params: Any = None) -> Any:
        global _jsonrpc_id
        _jsonrpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": _jsonrpc_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        resp = self._http.post_json("/rpc", payload)
        if resp.status != 200:
            raise AssertionError(f"RPC {method!r} returned HTTP {resp.status}: {resp.raw_text}")
        body = resp.json()
        if isinstance(body, dict) and "error" in body and body["error"] is not None:
            raise AssertionError(f"RPC {method!r} error: {body['error']}")
        return body.get("result") if isinstance(body, dict) else body
