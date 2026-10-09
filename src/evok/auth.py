""" Authentication of the API by one token of the configuration (apis: token),
    the origins of the web applications allowed to use it from a browser (apis: allowed_origins)

    Without a token the API is not authenticated, as before the option was added. A client sends
    the token as `Authorization: Bearer <token>`, as the password of Basic authentication with any
    user name, or to the WebSocket also as the query argument `token`, a browser cannot set a header
    of a WebSocket. The token is not accepted in the URL of the other APIs, it would be kept
    in the logs of proxies and in the history of browsers.

    The optional read_token gives the access only for reading: the requests which change a device
    raise ReadOnlyAccess, reported as 403.
"""
import base64
import binascii
import hmac
import json
from urllib.parse import urlparse

from .errors import ReadOnlyAccess
from .log import logger

WRITE, READ = 'write', 'read'       # the access of a request

_token: str | None = None
_read_token: str | None = None
_allowed_origins: frozenset[str] = frozenset()     # scheme://host[:port] in lower case


def set_token(token, read_token=None) -> None:
    """ Set the tokens of the configuration, None disables the authentication; raise ValueError if they are invalid """
    global _token, _read_token
    for name, value in (('token', token), ('read_token', read_token)):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"apis: '{name}' must be a non-empty string")
    if read_token is not None:
        # without the token the API would be open for changes and closed for reading
        if token is None:
            raise ValueError("apis: 'read_token' requires 'token'")
        if read_token == token:
            raise ValueError("apis: 'read_token' must differ from 'token'")
    _token, _read_token = token, read_token


def is_enabled() -> bool:
    return _token is not None


def set_allowed_origins(origins) -> None:
    """ Set the origins of the configuration, e.g. ['http://192.168.1.10:1880'];
        raise ValueError if they are invalid
    """
    global _allowed_origins
    if origins is None:
        origins = []
    if not isinstance(origins, list):
        raise ValueError("apis: 'allowed_origins' must be a list of origins, e.g. http://192.168.1.10:1880")
    allowed = set()
    for origin in origins:
        parsed = urlparse(origin.strip()) if isinstance(origin, str) else None
        if parsed is None or parsed.scheme not in ('http', 'https') or not parsed.netloc \
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise ValueError(f"apis: invalid origin {origin!r} in 'allowed_origins', e.g. http://192.168.1.10:1880")
        allowed.add(f"{parsed.scheme}://{parsed.netloc}".lower())
    _allowed_origins = frozenset(allowed)


def is_allowed_origin(origin: str) -> bool:
    """ The origin of a web application is in allowed_origins of the configuration """
    return origin.strip().rstrip('/').lower() in _allowed_origins


def is_same_origin(origin: str, request) -> bool:
    """ The origin is the host of the request, also the host forwarded by a proxy, e.g. nginx;
        a browser cannot set X-Forwarded-Host of a WebSocket, a client which can needs no origin
    """
    # Node-RED sends the origin without the scheme
    netloc = urlparse(origin).netloc if '://' in origin else origin
    hosts = [request.host, request.headers.get('X-Forwarded-Host', '')]
    return bool(netloc) and netloc.lower() in (host.split(',')[0].strip().lower() for host in hosts if host)


def _request_token(request, query_token: bool) -> str | None:
    """ The token sent by the request, None without one """
    scheme, _, value = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() == 'bearer':
        return value.strip()
    if scheme.lower() == 'basic':
        try:
            _, _, password = base64.b64decode(value.strip(), validate=True).decode().partition(':')
        except (binascii.Error, UnicodeDecodeError):
            return None
        return password
    if query_token:
        values = request.query_arguments.get('token')
        if values:
            return values[-1].decode(errors='replace')
    return None


def _equal(token: str, configured: str | None) -> bool:
    # in constant time, the time of the comparison does not tell a part of the token
    return configured is not None and hmac.compare_digest(token.encode(), configured.encode())


def access(request, query_token: bool = False) -> str | None:
    """ WRITE for the token or without the token configured, READ for the read_token, None without a valid one """
    if _token is None:
        return WRITE
    token = _request_token(request, query_token)
    if token is None:
        return None
    # both are compared, the time does not tell which one matched
    write, read = _equal(token, _token), _equal(token, _read_token)
    return WRITE if write else READ if read else None


def is_authorized(request, query_token: bool = False) -> bool:
    """ The request has a token of the configuration, any request without the token configured """
    return access(request, query_token) is not None


class TokenAuth:
    """ Mixin of the handlers of the API, it is before tornado.web.RequestHandler in the bases

        prepare() refuses a request without the token by 401 before its method, a WebSocket before
        the upgrade. A preflight OPTIONS of a browser has no token, it is not checked.
    """

    auth_exempt = False     # e.g. /version for monitoring
    query_token = False     # the token also in the query argument token, only the WebSocket
    access = WRITE          # of the request, set by prepare()

    def set_default_headers(self):
        """ CORS only for the allowed origins of the configuration, it was * for every web page;
            a request from the same origin as the API needs no CORS
        """
        self.set_header('Vary', 'Origin')
        origin = self.request.headers.get('Origin')
        if origin is not None and is_allowed_origin(origin):
            self.set_header('Access-Control-Allow-Origin', origin)
            self.set_header('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Requested-With')

    def require_write(self):
        """ Raise ReadOnlyAccess for a request with the read_token, call it before a change """
        if self.access != WRITE:
            raise ReadOnlyAccess("The token allows only reading")

    def prepare(self):
        if self.auth_exempt or self.request.method == 'OPTIONS':
            return
        request_access = access(self.request, self.query_token)
        if request_access is not None:
            self.access = request_access
            return
        logger.warning(f"Unauthorized {self.request.method} {self.request.path} from {self.request.remote_ip}")
        self.set_status(401)
        self.add_header('WWW-Authenticate', 'Bearer realm="evok"')
        self.add_header('WWW-Authenticate', 'Basic realm="evok"')
        self.set_header('Content-Type', 'application/json')
        self.finish(json.dumps({'success': False, 'errors': {'Unauthorized': 'Missing or invalid token'}}))
