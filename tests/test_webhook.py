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


def webhook(allowed_types, complex_events=True, error=None, min_interval=0.05):
    wh = WhHandler('http://127.0.0.1:1/hook', allowed_types, complex_events, min_interval)
    wh.http_client = FakeHttpClient(error)
    return wh


async def sent_requests(wh):
    """ Wait until the pending states are sent """
    if wh.send_task is not None:
        await wh.send_task
    return wh.http_client.requests


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
    assert await sent_requests(wh) == ([('POST', sent)] if sent else [])


async def test_simple_event():
    wh = webhook(['wd'], complex_events=False)
    wh.on_event(FakeState(WD_STATE))
    assert await sent_requests(wh) == [('GET', None)]


async def test_request_error_is_logged(caplog):
    wh = webhook(['di'], error=ConnectionRefusedError('refused'))
    wh.on_event(FakeState(DI_STATE))
    await sent_requests(wh)
    assert 'refused' in caplog.text
    assert wh.send_task is None


async def test_changes_are_merged():
    wh = webhook(['di'])
    di_on, di_off = {'dev': 'di', 'circuit': '1_01', 'value': 1}, {'dev': 'di', 'circuit': '1_01', 'value': 0}
    di_2 = {'dev': 'di', 'circuit': '1_02', 'value': 1}
    wh.on_event(FakeState(di_on))       # sent at once
    await asyncio.sleep(0)
    wh.on_event(FakeState(di_off))      # merged into the second request
    wh.on_event(FakeState(di_2, di_on))
    assert await sent_requests(wh) == [('POST', [di_on]), ('POST', [di_on, di_2])]


async def test_min_interval():
    wh = webhook(['di'], min_interval=0.1)
    loop = asyncio.get_running_loop()
    start = loop.time()
    wh.on_event(FakeState(DI_STATE))
    await sent_requests(wh)
    assert loop.time() - start < 0.05                  # the first change is sent immediately
    wh.on_event(FakeState(DI_STATE))
    await sent_requests(wh)
    assert loop.time() - start >= 0.1                  # the next one after min_interval
    assert len(wh.http_client.requests) == 2


async def test_one_request_at_a_time():
    wh = webhook(['di'], min_interval=0)
    release = asyncio.Event()
    active, max_active = 0, 0

    async def slow_fetch(url, method, headers, body=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await release.wait()
        active -= 1
        wh.http_client.requests.append(json.loads(body))
    wh.http_client.fetch = slow_fetch
    for value in range(10):
        wh.on_event(FakeState({'dev': 'di', 'circuit': '1_01', 'value': value}))
        await asyncio.sleep(0)
    release.set()
    await sent_requests(wh)
    # the first request and one request with the last state
    assert wh.http_client.requests == [[{'dev': 'di', 'circuit': '1_01', 'value': 0}],
                                       [{'dev': 'di', 'circuit': '1_01', 'value': 9}]]
    assert max_active == 1
