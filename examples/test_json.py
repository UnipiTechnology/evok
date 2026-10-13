import json

import requests

host = '192.168.221.169'


def set_rest_request(host: str, dev_type: str, dev_id: str, data=None, value=None):
    url = f"http://{host}/json/{dev_type}/{dev_id}"
    data = {'value': value} if value is not None else data
    return requests.post(url=url, data=json.dumps(data))


def get_rest_request(host: str, dev_type: str, dev_id: str, value=None):
    url = f"http://{host}/json/{dev_type}/{dev_id}"
    return requests.get(url=url)


def main():
    # ret = set_rest_request(host=host, dev_type='owpower', dev_id='1', value='1')
    # ret = set_rest_request(host=host, dev_type='owbus', dev_id='OWFS', data={'do_scan': True})
    ret = set_rest_request(host=host, dev_type='owbus', dev_id='OWFS', data={'do_reset': True})
    print(ret.json())


if __name__ == '__main__':
    main()
