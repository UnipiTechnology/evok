import requests

host = '127.0.0.1'


def main():
    url = f"http://{host}/rpc"

    # the state of a relay
    payload_get = {
        "method": "relay_get",
        "params": ["xs51_01"],
        "jsonrpc": "2.0",
        "id": 0,
    }
    response = requests.post(url, json=payload_get).json()
    print(response)


if __name__ == "__main__":
    main()
