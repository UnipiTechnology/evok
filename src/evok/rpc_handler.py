#!/usr/bin/python
import base64
import functools
import inspect
from typing import Awaitable, Optional

from tornado_jsonrpc2 import JSONRPCHandler
from tornado_jsonrpc2.exceptions import MethodNotFound, InvalidParams

from .devices import SENSOR, OWBUS, DI, DO, RO, AI, AO
from .devices import Devices, DeviceNotFound


async def create_response(request, backend):
    if request.method not in backend.RPC_METHODS:
        raise MethodNotFound(f"Method '{request.method}' not found!")
    method = getattr(backend, request.method)

    awaitable = False
    if inspect.isawaitable(method) or inspect.iscoroutine(method) or inspect.iscoroutinefunction(method):
        awaitable = True

    try:
        try:
            params = request.params
        except AttributeError:
            if awaitable:
                return await method()
            else:
                return method()

        if isinstance(params, list):
            if awaitable:
                return await method(*params)
            else:
                return method(*params)
        elif isinstance(params, dict):
            if awaitable:
                return await method(**params)
            else:
                return method(**params)
    except DeviceNotFound as e:
        raise InvalidParams(e)


class UserBasicHelper(JSONRPCHandler):
    _passwords = []

    def initialize(self, response_creator: Awaitable = None, version: Optional[str] = None):
        if response_creator is None:
            response_creator = functools.partial(create_response,
                                                 backend=self)
        super().initialize(response_creator=response_creator, version=version)

    def _request_auth(self):
        self.set_header('WWW-Authenticate', 'Basic realm=tmr')
        self.set_status(401)
        self.finish()

    def get_current_user(self):
        if len(self._passwords) == 0:
            return True
        auth_header = self.request.headers.get('Authorization')
        if auth_header is None or not auth_header.startswith('Basic '):
            return False
        try:
            username, password = base64.b64decode(auth_header[6:]).decode().split(':', 1)
        except ValueError:
            # invalid base64, invalid utf-8 or missing ':'
            return False
        return username == 'rpc' and password in self._passwords


class Handler(UserBasicHelper):
    # methods callable via JSON-RPC, other attributes of the handler are not exposed
    RPC_METHODS = frozenset((
        'input_get',
        'input_get_value',
        'input_set',
        'relay_get',
        'relay_set',
        'output_get',
        'output_set',
        'output_set_for_time',
        'ai_get',
        'ao_set_value',
        'ao_set',
        'owbus_get',
        'owbus_set',
        'owbus_scan',
        'owbus_list',
        'sensor_set',
        'sensor_get',
        'sensor_get_value',
    ))

    async def post(self):
        if not self.current_user:
            self._request_auth()
            return
        await JSONRPCHandler.post(self)

    # ---- Input ----
    def input_get(self, circuit):
        inp = Devices.by_name(DI, str(circuit))
        state = inp.get()
        return state['value'], state['debounce']

    def input_get_value(self, circuit):
        inp = Devices.by_name(DI, str(circuit))
        return inp.get()['value']

    async def input_set(self, circuit, debounce):
        inp = Devices.by_name(DI, str(circuit))
        await inp.set(debounce=debounce)
        return inp.full()

    # ---- Relay ----
    def relay_get(self, circuit):
        relay = Devices.by_name(RO, str(circuit))
        return relay.get()['value']

    async def relay_set(self, circuit, value):
        relay = Devices.by_name(RO, str(circuit))
        value = 1 if value else 0
        await relay.set(value=value)
        return value

    def output_get(self, circuit):
        relay = Devices.by_name(DO, str(circuit))
        state = relay.get()
        return state['value'], state['pending']

    async def output_set(self, circuit, value):
        relay = Devices.by_name(DO, str(circuit))
        value = 1 if value else 0
        await relay.set(value=value)
        return value

    async def output_set_for_time(self, circuit, value, timeout):
        relay = Devices.by_name(DO, str(circuit))
        if timeout <= 0:
            raise ValueError('Invalid timeout %s' % str(timeout))
        await relay.set(value, timeout)
        return relay.full()

    # ---- Analog Input ----
    def ai_get(self, circuit):
        ai = Devices.by_name(AI, str(circuit))
        return ai.get()

    # def ai_measure(self, circuit):

    # ---- Analog Output (0-10V) ----
    async def ao_set_value(self, circuit, value):
        ao = Devices.by_name(AO, str(circuit))
        return await ao.set_value(value)

    async def ao_set(self, circuit, value, mode):
        ao = Devices.by_name(AO, str(circuit))
        await ao.set(value, mode)
        return ao.full()

    # ---- OwBus (1wire bus) ----
    def owbus_get(self, circuit):
        ow = Devices.by_name(OWBUS, str(circuit))
        return ow.bus_driver.scan_interval

    async def owbus_set(self, circuit, scan_interval):
        ow = Devices.by_name(OWBUS, str(circuit))
        await ow.bus_driver.set(scan_interval=scan_interval)
        return ow.bus_driver.full()

    async def owbus_scan(self, circuit):
        ow = Devices.by_name(OWBUS, str(circuit))
        await ow.bus_driver.set(do_scan=True)
        return ow.bus_driver.full()

    def owbus_list(self, circuit):
        ow = Devices.by_name(OWBUS, str(circuit))
        return ow.bus_driver.list()

    # ---- Sensors (1wire thermo,humidity) ----
    async def sensor_set(self, circuit, interval):
        sens = Devices.by_name(SENSOR, str(circuit))
        await sens.set(interval=interval)
        return sens.full()

    def sensor_get(self, circuit):
        sens = Devices.by_name(SENSOR, str(circuit))
        return sens.get()

    def sensor_get_value(self, circuit):
        sens = Devices.by_name(SENSOR, str(circuit))
        return sens.get_value()
