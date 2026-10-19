"""HTTP client for the REST / JSON / Bulk / RPC endpoints of a running Evok.

Every device state of a response and the params of every POST of a device are
validated against the definition of the API (oracles.contract).
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..oracles.contract import validate_input, validate_response


@dataclass
class HttpResponse:
    status: int
    body: Any  # parsed JSON when content-type is json, else raw text
    raw_text: str
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return self.body


class HttpClient:
    """Typed HTTP client, one per test (see the fixture)."""

    def __init__(self, base_url: str, token: str | None = None) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path: str) -> HttpResponse:
        return self._exchange("GET", path)

    def post_form(self, path: str, data: dict[str, Any]) -> HttpResponse:
        return self._exchange("POST", path, form=data)

    def post_json(self, path: str, body: Any) -> HttpResponse:
        return self._exchange("POST", path, json_body=body)

    def _exchange(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> HttpResponse:
        path = path if path.startswith("/") else f"/{path}"
        url = f"{self._base}{path}"
        with httpx.Client(timeout=5.0, headers=self._headers) as client:
            if method == "GET":
                r = client.get(url)
            elif json_body is not None:
                r = client.post(url, json=json_body)
            else:
                r = client.post(url, data=form or {})
        resp = _httpx_to_response(r)
        validate_states(f"{method} {path}", resp.body)
        if method == "POST" and resp.status == 200:
            # params out of the definition must be refused, a test of an error sends them on purpose
            _validate_params(method, path, form if form is not None else json_body, resp.body)
        return resp


def _httpx_to_response(r: httpx.Response) -> HttpResponse:
    raw = r.text
    body: Any
    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError):
        body = raw
    return HttpResponse(
        status=r.status_code,
        body=body,
        raw_text=raw,
        headers={k.lower(): v for k, v in r.headers.items()},
    )


def _states(body: Any) -> list[dict]:
    """The device states of a reply: a state, a list of them, the result of a POST, of bulk"""
    if isinstance(body, list):
        return [state for item in body for state in _states(item)]
    if not isinstance(body, dict):
        return []
    if "dev" in body and "circuit" in body:
        return [body]
    states = []
    for key in ("result", "group_queries", "group_assignments", "individual_assignments"):
        if key in body:
            states.extend(_states(body[key]))
    return states


def validate_states(what: str, body: Any) -> None:
    """Validate the device states of a reply against the definition of the API"""
    errors = []
    for state in _states(body):
        errs = validate_response(state)
        if errs:
            errors.append(
                f"{state.get('dev', '?')}/{state.get('circuit', '?')}: " + "; ".join(errs)
            )
    if errors:
        raise AssertionError(f"{what}: contract violation(s):\n  " + "\n  ".join(errors))


def _validate_params(method: str, path: str, body: Any, reply: Any) -> None:
    """The params of an accepted POST of a device are in the definition of the API"""
    if not isinstance(body, dict):
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) != 3 or parts[0] not in ("rest", "json"):
        return  # /rpc, /bulk, a property or alias
    params = dict(body)
    errs = validate_input(parts[1], params)
    result = reply.get("result") if isinstance(reply, dict) else None
    if not errs and isinstance(result, dict) and "dev" in result:
        errs = validate_input(result["dev"], params)
    if errs:
        raise AssertionError(
            f"{method} {path}: accepted params {params} out of the definition of the API:\n  "
            + "\n  ".join(errs)
        )
