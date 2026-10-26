""" The token of the API (apis: token), checked by all handlers """
import base64
import json

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.web
import tornado.websocket

from evok import auth
from evok.bulk_handler import JSONBulkHandler
from evok.evok import LegacyJsonHandler, LegacyRestHandler, LoadAllHandler, LogHandler, VersionHandler
from evok.rpc_handler import Handler as RpcHandler
from evok.ws_handler import WsHandler

TOKEN = 'secret-token'


@pytest.fixture
def token():
    auth.set_token(TOKEN)
    yield TOKEN
    auth.set_token(None)


@pytest.fixture
async def server():
    sock, port = tornado.testing.bind_unused_port()
    http_server = tornado.httpserver.HTTPServer(tornado.web.Application([
        (r"/rest/all/?", LoadAllHandler),
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
        (r"/bulk/?", JSONBulkHandler),
        (r"/version/?", VersionHandler),
        (r"/log/?", LogHandler, {'log_file': None}),
        (r"/rpc/?", RpcHandler),
        (r"/ws/?", WsHandler),
    ]))
    http_server.add_sockets([sock])
    yield port
    http_server.stop()


# every API with a request which succeeds with the token
REQUESTS = {
    'rest': ('/rest/all', 'GET', None, 200),
    'rest post': ('/rest/di/1_01', 'POST', 'value=1', 404),            # no device, but authorized
    'json': ('/json/di/1_01', 'GET', None, 404),
    'bulk': ('/bulk', 'POST', '{}', 200),
    'log': ('/log', 'GET', None, 404),                                  # logging to a file is not configured
    'rpc': ('/rpc', 'POST', json.dumps({'jsonrpc': '2.0', 'method': 'relay_get', 'params': ['1_01'], 'id': 1}),
            200),
}


async def fetch(port, path, method='GET', body=None, headers=None):
    response = await tornado.httpclient.AsyncHTTPClient().fetch(
        f"http://127.0.0.1:{port}{path}", method=method, body=body, headers=headers, raise_error=False)
    return response


def basic(password, user='any'):
    return {'Authorization': 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()}


@pytest.mark.parametrize('api', REQUESTS)
async def test_api_is_open_without_token(server, api):
    path, method, body, code = REQUESTS[api]
    assert (await fetch(server, path, method, body)).code == code


@pytest.mark.parametrize('api', REQUESTS)
@pytest.mark.parametrize('headers', [None, {'Authorization': 'Bearer wrong'}, basic('wrong'),
                                     {'Authorization': 'Basic !!!'}, {'Authorization': 'Token secret-token'}])
async def test_api_refuses_request_without_token(server, token, api, headers):
    path, method, body, _ = REQUESTS[api]
    response = await fetch(server, path, method, body, headers)
    assert response.code == 401
    assert response.headers.get_list('WWW-Authenticate') == ['Bearer realm="evok"', 'Basic realm="evok"']
    assert json.loads(response.body) == {'success': False, 'errors': {'Unauthorized': 'Missing or invalid token'}}


@pytest.mark.parametrize('api', REQUESTS)
@pytest.mark.parametrize('headers', [{'Authorization': f'Bearer {TOKEN}'}, {'Authorization': f'bearer {TOKEN}'},
                                     basic(TOKEN), basic(TOKEN, user='rpc')])
async def test_api_accepts_token(server, token, api, headers):
    path, method, body, code = REQUESTS[api]
    assert (await fetch(server, path, method, body, headers)).code == code


async def test_token_in_url_is_refused_by_http_api(server, token):
    """ The token in the URL would be kept in the logs of proxies and in the history of browsers """
    assert (await fetch(server, f'/rest/all?token={TOKEN}')).code == 401


async def test_preflight_and_version_without_token(server, token):
    """ A browser sends no token in a preflight, /version is for monitoring """
    assert (await fetch(server, '/rest/all', 'OPTIONS')).code == 204
    assert (await fetch(server, '/bulk', 'OPTIONS')).code == 204
    assert (await fetch(server, '/version')).code == 200


async def test_unauthorized_request_is_logged_without_token(server, token, caplog):
    await fetch(server, '/rest/all', headers={'Authorization': 'Bearer wrong-value'})
    assert 'Unauthorized GET /rest/all from 127.0.0.1' in caplog.text
    assert 'wrong-value' not in caplog.text


async def ws_connect(port, query='', headers=None):
    request = tornado.httpclient.HTTPRequest(f"ws://127.0.0.1:{port}/ws{query}", headers=headers)
    return await tornado.websocket.websocket_connect(request)


@pytest.mark.parametrize('query, headers', [('', None), ('?token=wrong', None),
                                            ('', {'Authorization': 'Bearer wrong'})])
async def test_websocket_refuses_connection_without_token(server, token, query, headers):
    with pytest.raises(tornado.httpclient.HTTPClientError) as error:
        await ws_connect(server, query, headers)
    assert error.value.code == 401


@pytest.mark.parametrize('query, headers', [(f'?token={TOKEN}', None),
                                            ('', {'Authorization': f'Bearer {TOKEN}'}), ('', basic(TOKEN))])
async def test_websocket_accepts_token(server, token, query, headers):
    connection = await ws_connect(server, query, headers)
    await connection.write_message(json.dumps({'cmd': 'all'}))
    assert isinstance(json.loads(await connection.read_message()), list)
    connection.close()


async def test_websocket_without_token_configured(server):
    connection = await ws_connect(server)
    connection.close()


@pytest.mark.parametrize('token', [None, 'x'])
def test_valid_token(token):
    auth.set_token(token)
    assert auth.is_enabled() is (token is not None)
    auth.set_token(None)


@pytest.mark.parametrize('token', ['', '   ', 123, ['x'], True])
def test_invalid_token_is_rejected(token):
    with pytest.raises(ValueError, match="'token' must be a non-empty string"):
        auth.set_token(token)
    assert not auth.is_enabled()


ALLOWED = 'http://192.168.1.10:1880'


@pytest.fixture
def allowed_origins():
    auth.set_allowed_origins([ALLOWED + '/'])
    yield ALLOWED
    auth.set_allowed_origins(None)


async def test_cors_only_for_allowed_origins(server, allowed_origins):
    """ Access-Control-Allow-Origin: * let every web page in a browser read and control the IOs """
    for path, method in (('/rest/all', 'GET'), ('/bulk', 'OPTIONS'), ('/version', 'GET')):
        response = await fetch(server, path, method, headers={'Origin': 'http://evil.example'})
        assert 'Access-Control-Allow-Origin' not in response.headers
        response = await fetch(server, path, method, headers={'Origin': ALLOWED})
        assert response.headers['Access-Control-Allow-Origin'] == ALLOWED
        assert 'Authorization' in response.headers['Access-Control-Allow-Headers']
        assert response.headers['Vary'] == 'Origin'


async def test_no_cors_without_allowed_origins(server):
    response = await fetch(server, '/rest/all', headers={'Origin': ALLOWED})
    assert 'Access-Control-Allow-Origin' not in response.headers


@pytest.mark.parametrize('origin', ['http://evil.example', 'http://192.168.1.10:1881'])
async def test_websocket_refuses_other_origin(server, allowed_origins, origin):
    """ Every web page in a browser could connect to the WebSocket and control the IOs """
    with pytest.raises(tornado.httpclient.HTTPClientError) as error:
        await ws_connect(server, headers={'Origin': origin})
    assert error.value.code == 403


@pytest.mark.parametrize('origin, headers', [
    (ALLOWED, {}),
    ('http://127.0.0.1:{port}', {}),                                    # the same host
    ('127.0.0.1:{port}', {}),                                           # Node-RED sends no scheme
    ('http://plc.local', {'X-Forwarded-Host': 'plc.local'}),            # behind nginx
    (None, {}),                                                         # not a browser
])
async def test_websocket_accepts_origin(server, allowed_origins, origin, headers):
    if origin is not None:
        headers = dict(headers, Origin=origin.format(port=server))
    connection = await ws_connect(server, headers=headers)
    connection.close()


@pytest.mark.parametrize('origins', ['http://a', [1], ['ftp://a'], ['http://'], ['http://a/path'], ['a:80']])
def test_invalid_allowed_origins_are_rejected(origins):
    with pytest.raises(ValueError, match='allowed_origins'):
        auth.set_allowed_origins(origins)


READ_TOKEN = 'read-only-token'
READ = {'Authorization': f'Bearer {READ_TOKEN}'}
WRITE = {'Authorization': f'Bearer {TOKEN}'}


@pytest.fixture
def read_token():
    auth.set_token(TOKEN, READ_TOKEN)
    yield READ_TOKEN
    auth.set_token(None)


@pytest.mark.parametrize('path', ['/rest/all', '/json/di/1_01', '/log'])
async def test_read_token_reads(server, read_token, path):
    assert (await fetch(server, path, headers=READ)).code in (200, 404)    # authorized, 404 of no device or log


@pytest.mark.parametrize('path, body', [('/rest/di/1_01', 'debounce=10'), ('/json/di/1_01', '{"debounce": 10}')])
async def test_read_token_cannot_change(server, read_token, path, body):
    response = await fetch(server, path, 'POST', body, READ)
    assert response.code == 403
    assert json.loads(response.body) == {'success': False,
                                         'errors': {'ReadOnlyAccess': 'The token allows only reading'}}
    assert (await fetch(server, path, 'POST', body, WRITE)).code == 404     # the token for changes, no device


async def test_read_token_in_bulk(server, read_token):
    queries = json.dumps({'group_queries': [{'device_types': ['di']}]})
    assert (await fetch(server, '/bulk', 'POST', queries, READ)).code == 200
    # an assignment refuses the whole request before the lookup of its device, also its queries
    mixed = json.dumps({'group_queries': [{'device_types': ['di']}], 'individual_assignments': [
        {'device_type': 'di', 'device_circuit': '1_99', 'assigned_values': {'debounce': 1}}]})
    response = await fetch(server, '/bulk', 'POST', mixed, READ)
    assert response.code == 403 and 'group_queries' not in json.loads(response.body)
    assert (await fetch(server, '/bulk', 'POST', mixed, WRITE)).code == 404


async def test_read_token_in_rpc(server, read_token):
    async def call(method, params, headers):
        body = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1})
        return json.loads((await fetch(server, '/rpc', 'POST', body, headers)).body)
    assert (await call('relay_get', ['1_01'], READ))['error']['code'] == -32602      # read, no device
    assert (await call('relay_set', ['1_01', 1], READ))['error'] == \
        {'code': -32001, 'message': 'Forbidden: The token allows only reading'}
    assert (await call('relay_set', ['1_01', 1], WRITE))['error']['code'] == -32602  # changed, no device


def test_rpc_read_methods_are_rpc_methods():
    assert RpcHandler.RPC_READ_METHODS < RpcHandler.RPC_METHODS
    assert all(not ('_set' in method or 'scan' in method) for method in RpcHandler.RPC_READ_METHODS)


async def test_read_token_in_websocket(server, read_token):
    connection = await ws_connect(server, f'?token={READ_TOKEN}')
    await connection.write_message(json.dumps({'cmd': 'all'}))
    assert isinstance(json.loads(await connection.read_message()), list)
    await connection.write_message(json.dumps({'cmd': 'set', 'dev': 'di', 'circuit': '1_99', 'debounce': 1}))
    assert json.loads(await connection.read_message()) == \
        {'success': False, 'errors': {'ReadOnlyAccess': 'The token allows only reading'}}
    connection.close()


@pytest.mark.parametrize('token, read, error', [
    (None, 'x', "'read_token' requires 'token'"),
    ('x', 'x', "'read_token' must differ from 'token'"),
    ('x', '', "'read_token' must be a non-empty string"),
])
def test_invalid_read_token_is_rejected(token, read, error):
    with pytest.raises(ValueError, match=error):
        auth.set_token(token, read)
    assert not auth.is_enabled()


@pytest.mark.parametrize('origin, host, same', [
    ('http://192.168.221.159', '192.168.221.159:80', True),     # nginx of evok-web forwards host:port
    ('http://plc', 'plc:80', True),
    ('https://plc', 'plc:443', True),
    ('http://plc:80', 'plc', True),
    ('http://PLC.local', 'plc.local', True),
    ('http://[::1]', '[::1]:80', True),
    ('http://plc:8080', 'plc:8080', True),
    ('127.0.0.1:1880', '127.0.0.1:1880', True),                 # Node-RED, no scheme
    ('https://plc', 'plc:80', False),
    ('http://plc', 'plc:8080', False),
    ('http://plc', 'other:80', False),
    ('http://plc', 'plc:abc', False),
    ('', 'plc', False),
])
def test_same_origin_with_the_default_port(origin, host, same):
    """ The WebSocket of evok-web behind its nginx (Host: host:80) was refused, the origin has no default port """
    from types import SimpleNamespace
    assert auth.is_same_origin(origin, SimpleNamespace(host=host, headers={})) is same


def test_same_origin_by_the_forwarded_host():
    from types import SimpleNamespace
    request = SimpleNamespace(host='127.0.0.1:8080', headers={'X-Forwarded-Host': 'plc.local:80, proxy'})
    assert auth.is_same_origin('http://plc.local', request)


@pytest.mark.parametrize('configured, origin, allowed', [
    ('http://a', 'http://a:80', True),
    ('https://a:443', 'https://a', True),
    ('http://A:1880/', 'http://a:1880', True),
    ('http://a', 'http://a:8080', False),
    ('http://a', 'https://a', False),
])
def test_allowed_origins_with_the_default_port(configured, origin, allowed):
    auth.set_allowed_origins([configured])
    try:
        assert auth.is_allowed_origin(origin) is allowed
    finally:
        auth.set_allowed_origins(None)


@pytest.fixture
def trusted_downstream():
    """ nginx of evok-web on the controller and a proxy of the network """
    auth.set_trusted_downstream(['127.0.0.1', '10.0.0.0/8'])
    yield
    auth.set_trusted_downstream(None)


def request_from(remote_ip, **headers):
    from types import SimpleNamespace
    headers = {key.replace('_', '-'): value for key, value in headers.items()}
    return SimpleNamespace(remote_ip=remote_ip, headers=headers)


@pytest.mark.parametrize('request_, client', [
    (request_from('127.0.0.1', X_Forwarded_For='192.168.1.20'), '192.168.1.20'),
    (request_from('127.0.0.1', X_Real_IP='192.168.1.20'), '192.168.1.20'),
    (request_from('127.0.0.1', X_Forwarded_For='192.168.1.20', X_Real_IP='192.168.1.99'), '192.168.1.20'),
    # the client prepends a forged address, the proxies append the real one
    (request_from('127.0.0.1', X_Forwarded_For='1.2.3.4, 192.168.1.20, 10.0.0.5'), '192.168.1.20'),
    (request_from('127.0.0.1', X_Forwarded_For='10.0.0.6, 10.0.0.5'), '10.0.0.6'),     # only proxies
    (request_from('127.0.0.1', X_Forwarded_For='nonsense'), '127.0.0.1'),
    (request_from('127.0.0.1', X_Real_IP='nonsense'), '127.0.0.1'),
    (request_from('127.0.0.1'), '127.0.0.1'),
    (request_from('::1', X_Forwarded_For='192.168.1.20'), '::1'),                       # not a trusted proxy
    (request_from('192.168.1.30', X_Forwarded_For='1.2.3.4', X_Real_IP='1.2.3.4'), '192.168.1.30'),
])
def test_client_ip_by_a_trusted_proxy(trusted_downstream, request_, client):
    assert auth.client_ip(request_) == client


def test_client_ip_without_trusted_downstream():
    """ The headers are ignored by default, any client could forge them """
    assert auth.client_ip(request_from('127.0.0.1', X_Forwarded_For='1.2.3.4', X_Real_IP='1.2.3.4')) == '127.0.0.1'


@pytest.mark.parametrize('proxies', ['127.0.0.1', ['localhost'], [1], ['10.0.0.0/33'], ['']])
def test_invalid_trusted_downstream_is_rejected(proxies):
    with pytest.raises(ValueError, match='trusted_downstream'):
        auth.set_trusted_downstream(proxies)


async def test_unauthorized_request_is_logged_with_the_client_of_the_proxy(server, token, trusted_downstream, caplog):
    await fetch(server, '/rest/all', headers={'X-Forwarded-For': '192.168.1.20', 'X-Real-IP': '192.168.1.20'})
    assert 'Unauthorized GET /rest/all from 192.168.1.20' in caplog.text


async def test_unauthorized_request_is_logged_without_the_headers_of_a_client(server, token, caplog):
    await fetch(server, '/rest/all', headers={'X-Forwarded-For': '1.2.3.4', 'X-Real-IP': '1.2.3.4'})
    assert 'Unauthorized GET /rest/all from 127.0.0.1' in caplog.text
