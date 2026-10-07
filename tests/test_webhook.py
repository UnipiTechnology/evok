import asyncio
import json

import pytest

from evok.evok import WhHandler


class FakeState:
    def __init__(self, *states):
        self.states = states

    def full(self):
        return list(self.states) if len(self.states) > 1 else self.states[0]


class FakeHttpClient:
    def __init__(self, error=None):
        self.requests = []
        self.error = error

    def fetch(self, url, method, headers, body=None):
        self.requests.append((method, json.loads(body) if body else None))
        future = asyncio.get_running_loop().create_future()
        if self.error:
            future.set_exception(self.error)
        else:
            future.set_result(None)
        return future


def webhook(allowed_types, complex_events=True, error=None):
    wh = WhHandler('http://127.0.0.1:1/hook', allowed_types, complex_events)
    wh.http_client = FakeHttpClient(error)
    return wh


DI_STATE = {'dev': 'di', 'circuit': '1_01'}
WD_STATE = {'dev': 'wd', 'circuit': '1'}
TEMP_STATE = {'dev': 'temp', 'circuit': '28AB'}


@pytest.mark.parametrize('event, sent', [
    (FakeState(DI_STATE, WD_STATE), [DI_STATE, WD_STATE]),     # Modbus devices, a list
    (FakeState(TEMP_STATE), [TEMP_STATE]),                     # a 1-Wire sensor, a dict
    (FakeState({'dev': 'ro', 'circuit': '1_01'}), None),       # not in the mask
])
async def test_default_mask(event, sent):
    wh = webhook(['di', 'sensor', 'watchdog'])
    wh.on_event(event)
    assert wh.http_client.requests == ([('POST', sent)] if sent else [])


async def test_simple_event():
    wh = webhook(['wd'], complex_events=False)
    wh.on_event(FakeState(WD_STATE))
    assert wh.http_client.requests == [('GET', None)]


async def test_request_error_is_logged(caplog):
    wh = webhook(['di'], error=ConnectionRefusedError('refused'))
    wh.on_event(FakeState(DI_STATE))
    await asyncio.sleep(0)
    assert 'refused' in caplog.text
