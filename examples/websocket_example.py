"""WebSocket API: the events of the digital inputs and the user LEDs, see docs/apis/websocket.md

The WebSocket is disabled by default, it needs 'websocket: enabled: true' in 'apis' of the configuration.
"""

import json
import os

import websocket

HOST = os.environ.get("EVOK_HOST", "127.0.0.1")
PORT = os.environ.get("EVOK_PORT", "8080")
TOKEN = os.environ.get("EVOK_TOKEN")  # the token of 'apis' in the configuration, if it is set
HEADER = [f"Authorization: Bearer {TOKEN}"] if TOKEN else []


def on_message(ws, message):
    print(f"Received message: {message}")


def on_error(ws, error):
    print(f"Encountered an error: {error}")


def on_close(ws, status, message):
    print("WebSocket connection closed")


def on_open(ws):
    # only the events of these device types, then the state of all of them and a change of a LED
    ws.send(json.dumps({"cmd": "filter", "devices": ["di", "led"]}))
    ws.send(json.dumps({"cmd": "full", "dev": "led", "circuit": "1_01"}))
    ws.send(json.dumps({"cmd": "set", "dev": "led", "circuit": "1_01", "value": 1}))


if __name__ == "__main__":
    app = websocket.WebSocketApp(
        f"ws://{HOST}:{PORT}/ws",
        header=HEADER,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    app.run_forever()
