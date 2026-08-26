"""In-process webhook receiver.

A tiny HTTP server the harness spins up so tests can assert Evok's *outbound*
POSTs (or GETs) without an external service. The Evok webhook target URL must
be configured to point at this receiver during live/record runs.
"""

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self


@dataclass
class WebhookCapture:
    posts: list[dict] = field(default_factory=list)
    gets: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        self.posts.clear()
        self.gets.clear()


class WebhookReceiver:
    """Runs a localhost HTTP server in a background thread; captures inbound hits."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8181) -> None:
        self.capture = WebhookCapture()
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> Self:
        capture = self.capture

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # silence
                pass

            def do_GET(self) -> None:
                capture.gets.append({"path": self.path, "headers": dict(self.headers)})
                self.send_response(200)
                self.end_headers()

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                try:
                    parsed = json.loads(body) if body else None
                except (ValueError, json.JSONDecodeError):
                    parsed = body.decode(errors="replace")
                capture.posts.append({"path": self.path, "body": parsed})
                self.send_response(200)
                self.end_headers()

        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._thread = None
