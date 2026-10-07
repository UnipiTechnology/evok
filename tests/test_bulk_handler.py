import json

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.web

from evok.bulk_handler import JSONBulkHandler
from evok.devices import Devices, DO, SENSOR, MODBUS_SLAVE


class FakeDevice:
    def __init__(self, devtype, circuit, major_group=None):
        self.devtype = devtype
        self.circuit = circuit
        self.alias = ''
        if major_group is not None:
            self.major_group = major_group
        self.calls = []

    def full(self):
        return {'dev': self.devtype, 'circuit': self.circuit}

    async def set(self, **kw):
        if kw.get('value') == 9:
            raise ValueError('Value out of range')
        self.calls.append(kw)


@pytest.fixture
def devices():
    Devices[DO]['1_01'] = FakeDevice(DO, '1_01', '1')
    Devices[DO]['2_01'] = FakeDevice(DO, '2_01', '2')
    Devices[SENSOR]['28AB'] = FakeDevice(SENSOR, '28AB', 1)          # 1-Wire, a number
    Devices[MODBUS_SLAVE]['1'] = FakeDevice(MODBUS_SLAVE, '1')       # no major_group
    return Devices


@pytest.fixture
async def bulk():
    sock, port = tornado.testing.bind_unused_port()
    server = tornado.httpserver.HTTPServer(tornado.web.Application([(r"/bulk", JSONBulkHandler)]))
    server.add_sockets([sock])

    async def request(body):
        response = await tornado.httpclient.AsyncHTTPClient().fetch(
            f"http://127.0.0.1:{port}/bulk", method='POST', body=json.dumps(body), raise_error=False)
        return response.code, json.loads(response.body)
    yield request
    server.stop()


@pytest.mark.parametrize('query, expected', [
    ({'device_types': ['do'], 'group': 1}, ['1_01']),
    ({'device_types': ['do'], 'group': '2'}, ['2_01']),
    ({'device_types': ['sensor'], 'group': 1}, ['28AB']),             # was never found
    ({'device_types': ['sensor'], 'group': '1'}, ['28AB']),
    ({'device_types': ['modbus_slave'], 'group': 1}, []),             # was an internal error
    ({'device_types': ['do'], 'device_circuits': ['2_01']}, ['2_01']),
])
async def test_group_queries(bulk, devices, query, expected):
    code, reply = await bulk({'group_queries': [query]})
    assert code == 200
    assert [state['circuit'] for state in reply['group_queries'][0]] == expected


async def test_group_assignment_by_group(bulk, devices):
    code, reply = await bulk({'group_assignments': [{'device_type': 'do', 'group': 2, 'assigned_values': {'value': 1}}]})
    assert code == 200
    assert (devices[DO]['1_01'].calls, devices[DO]['2_01'].calls) == ([], [{'value': 1}])


@pytest.mark.parametrize('invalid, code', [
    ({'device_type': 'do', 'device_circuit': '9_99', 'assigned_values': {'value': 1}}, 404),
    ({'device_type': 'do', 'device_circuit': '2_01', 'assigned_values': {'bogus': 1}}, 400),
])
async def test_nothing_is_set_before_an_invalid_command(bulk, devices, invalid, code):
    status, reply = await bulk({
        'group_assignments': [{'device_type': 'do', 'assigned_values': {'value': 1}}],
        'individual_assignments': [{'device_type': 'do', 'device_circuit': '1_01', 'assigned_values': {'value': 0}},
                                   invalid],
    })
    assert status == code
    assert (devices[DO]['1_01'].calls, devices[DO]['2_01'].calls) == ([], [])
    assert 'individual_assignments' not in reply


async def test_results_before_an_error_are_returned(bulk, devices):
    status, reply = await bulk({
        'individual_assignments': [
            {'device_type': 'do', 'device_circuit': '1_01', 'assigned_values': {'value': 1}},
            {'device_type': 'do', 'device_circuit': '2_01', 'assigned_values': {'value': 9}},     # fails in set()
            {'device_type': 'do', 'device_circuit': '1_01', 'assigned_values': {'value': 0}},
        ],
    })
    assert status == 400
    assert reply['errors'] == {'ValueError': 'Value out of range'}
    assert reply['individual_assignments'] == [{'dev': 'do', 'circuit': '1_01'}]
    assert devices[DO]['1_01'].calls == [{'value': 1}]
