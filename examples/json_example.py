"""JSON API: read a device and set a user LED by a JSON body, see docs/apis/json.md"""

import os

import requests

HOST = os.environ.get("EVOK_HOST", "127.0.0.1")
PORT = os.environ.get("EVOK_PORT", "8080")
TOKEN = os.environ.get("EVOK_TOKEN")  # the token of 'apis' in the configuration, if it is set
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def get_device(dev_type: str, circuit: str) -> dict:
    url = f"http://{HOST}:{PORT}/json/{dev_type}/{circuit}"
    return requests.get(url, headers=HEADERS, timeout=5).json()


def set_device(dev_type: str, circuit: str, **params) -> dict:
    """The params as a JSON object, the reply is {"success": true, "result": <the state after the change>}"""
    url = f"http://{HOST}:{PORT}/json/{dev_type}/{circuit}"
    return requests.post(url, json=params, headers=HEADERS, timeout=5).json()


def main():
    print(get_device("ai", "1_01"))
    print(set_device("led", "1_01", value=1))
    print(set_device("led", "1_01", value=0))
    # e.g. a search of the 1-Wire bus of the autogen: set_device("owbus", "OWBUS", do_scan=True)


if __name__ == "__main__":
    main()
