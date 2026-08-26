"""HTTP client for REST / JSON / Bulk endpoints with record/replay.

Server-agnostic: in ``live``/``record`` mode it issues real httpx requests; in
``replay`` mode it serves the recorded response from a cassette. The cassette
name is derived from the test (via ``cassette_name`` fixture) so each test owns
its golden slice.
"""

import json
from dataclasses import dataclass
from typing import Any

import httpx

from ..cassette import (
    ALLOW_NETWORK,
    BANK,
    DIFF_AGAINST_CASSETTE,
    PERSIST,
    diff_values,
    request_id,
)
from ..oracles.contract import validate_input, validate_response


@dataclass
class HttpResponse:
    status: int
    body: Any  # parsed JSON when content-type is json, else raw text
    raw_text: str

    def json(self) -> Any:
        return self.body


class HttpClient:
    """Typed, cassette-aware HTTP client. One per test (see fixture)."""

    def __init__(self, base_url: str, cassette_name: str) -> None:
        self._base = base_url.rstrip("/")
        self._cassette_name = cassette_name

    # -- public typed operations -------------------------------------------------
    def get(self, path: str) -> HttpResponse:
        return self._exchange("GET", path)

    def post_form(self, path: str, data: dict[str, Any]) -> HttpResponse:
        return self._exchange("POST", path, form=data)

    def post_json(self, path: str, body: Any, *, key: Any | None = None) -> HttpResponse:
        return self._exchange("POST", path, json_body=body, key=key)

    # -- core exchange: live / record / replay ----------------------------------
    def _exchange(
        self,
        method: str,
        path: str,
        *,
        form: dict[str, Any] | None = None,
        json_body: Any | None = None,
        key: Any | None = None,
    ) -> HttpResponse:
        path = path if path.startswith("/") else f"/{path}"
        rid = request_id(
            "http",
            cassette=self._cassette_name,
            method=method,
            path=path,
            form=form,
            json=key if key is not None else json_body,
        )
        cas = BANK.cassette(self._cassette_name)

        if not ALLOW_NETWORK:
            entry = cas.get(rid)
            if entry is None:
                raise AssertionError(
                    f"[replay] no cassette entry for {method} {path} "
                    f"(cassette={self._cassette_name!r}). Record it first with "
                    f"EVOK_TEST_MODE=record."
                )
            resp = _entry_to_response(entry["response"])
            _validate_contract(method, path, resp.body)
            # Validate the recorded write request against the input contract too.
            if method == "POST":
                rec_req = entry.get("request", {})
                rec_body = rec_req.get("form") or rec_req.get("json")
                _validate_input_contract(method, path, rec_body, None)
            return resp

        # live / record / compare: hit the real server
        url = f"{self._base}{path}"
        with httpx.Client(timeout=5.0) as client:
            if method == "GET":
                r = client.get(url)
            else:
                if json_body is not None:
                    r = client.post(url, json=json_body)
                else:
                    r = client.post(url, data=form or {})

        resp = _httpx_to_response(r)

        # compare mode: diff the fresh response against the recorded cassette.
        if DIFF_AGAINST_CASSETTE:
            entry = cas.get(rid)
            if entry is None:
                raise AssertionError(
                    f"[compare] no cassette entry to compare against for "
                    f"{method} {path} (cassette={self._cassette_name!r}). "
                    f"Record first with EVOK_TEST_MODE=record."
                )
            stored = entry["response"]
            _assert_http_matches(stored, resp, method, path)

        if PERSIST:
            cas.put(
                rid,
                {
                    "request": {
                        "kind": "http",
                        "method": method,
                        "path": path,
                        "form": form,
                        "json": json_body,
                    },
                    "response": {
                        "status": resp.status,
                        "body": resp.body,
                        "raw_text": resp.raw_text,
                    },
                },
            )
        return resp


def _httpx_to_response(r: httpx.Response) -> HttpResponse:
    raw = r.text
    body: Any
    try:
        body = r.json()
    except (ValueError, json.JSONDecodeError):
        body = raw
    return HttpResponse(status=r.status_code, body=body, raw_text=raw)


def _entry_to_response(stored: dict) -> HttpResponse:
    return HttpResponse(
        status=stored["status"],
        body=stored["body"],
        raw_text=stored.get("raw_text", ""),
    )


def _validate_contract(method: str, path: str, body: Any) -> None:
    """Validate every device payload in a response body against spec/spec.json.

    Runs in replay mode (offline CI gate). A regression that changes a field
    type, drops a required key, or leaves an enum/range fails here.
    """
    # Collect the device payload dicts from the body shape.
    payloads: list[dict] = []
    if isinstance(body, dict):
        if body.get("success") is False:
            return  # error envelope; not a device payload, no contract
        if "dev" in body and "circuit" in body:
            payloads.append(body)
        if isinstance(body.get("result"), dict) and "dev" in body["result"]:
            payloads.append(body["result"])
    elif isinstance(body, list):
        payloads.extend(e for e in body if isinstance(e, dict) and "dev" in e and "circuit" in e)
    all_errors = []
    for p in payloads:
        errs = validate_response(p)
        if errs:
            all_errors.append(f"{p.get('dev', '?')}/{p.get('circuit', '?')}: " + "; ".join(errs))
    if all_errors:
        raise AssertionError(
            f"[replay] {method} {path}: contract violation(s):\n  " + "\n  ".join(all_errors)
        )


def _validate_input_contract(method: str, path: str, body, _unused=None) -> None:
    """Validate a recorded POST request body against the input contract for its devtype."""
    if not isinstance(body, dict):
        return
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0] not in ("rest", "json"):
        return  # /rpc, /bulk — not devtype-keyed inputs
    dev = parts[1]
    errs = validate_input(dev, body)
    if errs:
        raise AssertionError(
            f"[replay] {method} {path}: input contract violation(s) for {dev}:\n  "
            + "\n  ".join(errs)
        )


def _assert_http_matches(stored: dict, live: HttpResponse, method: str, path: str) -> None:
    """Diff a live HTTP response against the recorded one; fail loudly on drift."""
    if stored["status"] != live.status:
        raise AssertionError(
            f"[compare] {method} {path}: status {live.status} != recorded {stored['status']}"
        )
    diffs = diff_values(stored["body"], live.body)
    if diffs:
        msg = f"[compare] {method} {path}: {len(diffs)} diff(s) vs cassette:\n  " + "\n  ".join(
            str(d) for d in diffs
        )
        raise AssertionError(msg)
