"""Bulk API: query the digital inputs and set the user LEDs in one request, see docs/apis/bulk.md"""

import os
import time

import requests

HOST = os.environ.get("EVOK_HOST", "127.0.0.1")
PORT = os.environ.get("EVOK_PORT", "8080")
TOKEN = os.environ.get("EVOK_TOKEN")  # the token of 'apis' in the configuration, if it is set
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

LEDS = ["1_01", "1_02", "1_03", "1_04"]


def bulk(request: dict) -> dict:
    return requests.post(f"http://{HOST}:{PORT}/bulk", json=request, headers=HEADERS, timeout=5).json()


def set_leds(value: int) -> dict:
    return bulk(
        {
            "group_queries": [{"device_types": ["di"]}],
            "individual_assignments": [
                {"device_type": "led", "device_circuit": circuit, "assigned_values": {"value": value}}
                for circuit in LEDS
            ],
        }
    )


def main():
    print(set_leds(1))
    time.sleep(2)
    print(set_leds(0))


if __name__ == "__main__":
    main()
