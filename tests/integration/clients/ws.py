"""WebSocket client with record/replay.

In ``live``/``record`` mode it opens a real ws connection and streams messages.
In ``replay`` mode it serves the recorded message stream from a cassette.

Cassette entries for WS are keyed by the *opening* request (url + optional
opening command) and store an ordered ``stream`` of received JSON messages. The
client records everything received until close, then (in record mode) persists
the whole stream under one entry.
"""

import asyncio
import json
from typing import Any, Self

from ..cassette import (
    ALLOW_NETWORK,
    BANK,
    DIFF_AGAINST_CASSETTE,
    PERSIST,
    diff_values,
    request_id,
)


class WsSession:
    """One logical WS exchange: open, (optionally) send a command, collect, close."""

    def __init__(self, base_url: str, cassette_name: str) -> None:
        # base_url is http://; ws uses the same host.
        self._ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        if not self._ws_url.endswith("/ws"):
            self._ws_url = self._ws_url.rstrip("/") + "/ws"
        self._cassette_name = cassette_name
        self._messages: list[Any] = []
        self._open_cmd: dict | None = None

    def will_send(self, cmd: dict | list[dict] | None) -> Self:
        # Accept a single command or a list sent sequentially after open.
        self._open_cmd = cmd
        return self

    async def run(self, receive_for: float = 1.0) -> list[Any]:
        rid = request_id(
            "ws",
            cassette=self._cassette_name,
            open_cmd=self._open_cmd,
        )
        cas = BANK.cassette(self._cassette_name)

        if not ALLOW_NETWORK:
            entry = cas.get(rid)
            if entry is None:
                raise AssertionError(
                    f"[replay] no WS cassette entry for open_cmd={self._open_cmd!r} "
                    f"(cassette={self._cassette_name!r}). Record it first."
                )
            return list(entry.get("stream", []))

        # live / record: open a real socket
        import websockets

        async with websockets.connect(self._ws_url, open_timeout=5) as ws:
            cmds = (
                self._open_cmd
                if isinstance(self._open_cmd, list)
                else ([self._open_cmd] if self._open_cmd is not None else [])
            )
            for cmd in cmds:
                await ws.send(json.dumps(cmd))
            try:
                end = asyncio.get_event_loop().time() + receive_for
                while asyncio.get_event_loop().time() < end:
                    raw = await asyncio.wait_for(
                        ws.recv(),
                        timeout=max(0.05, end - asyncio.get_event_loop().time()),
                    )
                    self._messages.append(json.loads(raw))
            except (TimeoutError, websockets.ConnectionClosed):
                pass

        if PERSIST:
            cas.put(
                rid,
                {
                    "request": {"kind": "ws", "open_cmd": self._open_cmd},
                    "stream": self._messages,
                },
            )

        # compare mode: diff the live stream against the recorded one.
        # WS streams are inherently timing-sensitive (server pushes arrive as
        # the scan loop ticks); we compare order-agnostically: every recorded
        # message must have an epsilon-matching counterpart in the live stream.
        if DIFF_AGAINST_CASSETTE:
            entry = cas.get(rid)
            if entry is None:
                raise AssertionError(
                    f"[compare] no WS cassette entry to compare against for "
                    f"open_cmd={self._open_cmd!r} (cassette={self._cassette_name!r})."
                )
            recorded_stream = list(entry.get("stream", []))
            _assert_ws_matches(recorded_stream, self._messages, self._open_cmd)
        return list(self._messages)


def _assert_ws_matches(recorded: list, live: list, open_cmd: Any) -> None:
    """Structural diff of two WS message streams.

    Contract: the FIRST recorded message (the `all`/`filter` snapshot, or the
    first event) must have an epsilon-matching counterpart in the live stream.
    Extra recorded messages beyond the first are event pushes whose count/timing
    depends on the scan loop and receive window -> NOT required (would cause
    false positives). Extra live messages are never a failure.

    This makes compare deterministic for WS despite non-deterministic event
    counts, while still catching the real regression: the snapshot's structure
    (device list, per-device fields) drifting.
    """
    if not recorded:
        return
    r0 = recorded[0]
    for j, lv in enumerate(live):
        if not diff_values(r0, lv, f"ws[0]~live[{j}]"):
            return  # first recorded message found a match -> pass
    # No match for the first message: report the best diffs.
    diffs = []
    for j, lv in enumerate(live):
        diffs.extend(diff_values(r0, lv, f"ws[0]~live[{j}]"))
    best = "\n  ".join(str(d) for d in diffs[:8])
    raise AssertionError(
        f"[compare] WS open_cmd={open_cmd!r}: recorded first message has no "
        f"epsilon-match in live stream ({len(live)} live msgs). First diffs:\n  {best}"
    )
