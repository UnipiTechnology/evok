""" Authentication of the API by one token of the configuration (apis: token)

    Without a token the API is not authenticated, as before the option was added. A client sends
    the token as `Authorization: Bearer <token>`, as the password of Basic authentication with any
    user name, or to the WebSocket also as the query argument `token`, a browser cannot set a header
    of a WebSocket. The token is not accepted in the URL of the other APIs, it would be kept
    in the logs of proxies and in the history of browsers.
"""
import base64
import binascii
import hmac
import json

from .log import logger

_token: str | None = None


def set_token(token) -> None:
    """ Set the token of the configuration, None disables the authentication; raise ValueError if it is invalid """
    global _token
    if token is not None and (not isinstance(token, str) or not token.strip()):
        raise ValueError("apis: 'token' must be a non-empty string")
    _token = token


def is_enabled() -> bool:
    return _token is not None


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


def is_authorized(request, query_token: bool = False) -> bool:
    """ The request has the token of the configuration, any request without the token configured """
    if _token is None:
        return True
    token = _request_token(request, query_token)
    # in constant time, the time of the comparison does not tell a part of the token
    return token is not None and hmac.compare_digest(token.encode(), _token.encode())


class TokenAuth:
    """ Mixin of the handlers of the API, it is before tornado.web.RequestHandler in the bases

        prepare() refuses a request without the token by 401 before its method, a WebSocket before
        the upgrade. A preflight OPTIONS of a browser has no token, it is not checked.
    """

    auth_exempt = False     # e.g. /version for monitoring
    query_token = False     # the token also in the query argument token, only the WebSocket

    def prepare(self):
        if self.auth_exempt or self.request.method == 'OPTIONS' or \
                is_authorized(self.request, self.query_token):
            return
        logger.warning(f"Unauthorized {self.request.method} {self.request.path} from {self.request.remote_ip}")
        self.set_status(401)
        self.add_header('WWW-Authenticate', 'Bearer realm="evok"')
        self.add_header('WWW-Authenticate', 'Basic realm="evok"')
        self.set_header('Content-Type', 'application/json')
        self.finish(json.dumps({'success': False, 'errors': {'Unauthorized': 'Missing or invalid token'}}))
