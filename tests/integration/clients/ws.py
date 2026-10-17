"""WebSocket client of a running Evok.

It opens a connection, sends the commands and collects the messages for a while;
every device state of the messages is validated against the definition of the API.
"""

import asyncio
import json
from typing import Any, Self

from .http import validate_states


class WsSession:
    """One logical WS exchange: open, (optionally) send a command, collect, close."""

    def __init__(self, base_url: str) -> None:
        # base_url is http://; ws uses the same host.
        self._ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
        if not self._ws_url.endswith("/ws"):
            self._ws_url = self._ws_url.rstrip("/") + "/ws"
        self._messages: list[Any] = []
        self._open_cmd: dict | list[dict] | None = None

    def will_send(self, cmd: dict | list[dict] | None) -> Self:
        # Accept a single command or a list sent sequentially after open.
        self._open_cmd = cmd
        return self

    async def run(self, receive_for: float = 1.0) -> list[Any]:
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
        for message in self._messages:
            validate_states(f"WS {self._open_cmd!r}", message)
        return list(self._messages)
