import functools
import inspect
from typing import Awaitable, Optional

from tornado_jsonrpc2 import JSONRPCHandler
from tornado_jsonrpc2.exceptions import InternalError, InvalidParams, MethodNotFound

from .auth import TokenAuth
from .devices import SENSOR, OWBUS, DI, DO, RO, AI, AO
from .devices import Devices, DeviceNotFound, to_bool
from .errors import UnitUnavailable
from .log import logger
from .modbus import set_devices


class UnitUnavailableError(InvalidParams):
    """ The Modbus unit failed its last scan or a request of the change failed

        A subclass of InvalidParams only for tornado_jsonrpc2, it returns any other error as InternalError,
        the error was -32603; the code and the message are its own.
    """
    error_code = -32000         # a server error defined by the implementation
    short_message = "Unit unavailable"


async def create_response(request, backend):
    if request.method not in backend.RPC_METHODS:
        raise MethodNotFound(f"Method '{request.method}' not found!")
    method = getattr(backend, request.method)

    params = getattr(request, 'params', [])
    if isinstance(params, list):
        args, kwargs = params, {}
    elif isinstance(params, dict):
        args, kwargs = [], params
    else:
        raise InvalidParams("Params must be an array or an object")
    # missing or unknown params are an error of the request, not an internal error
    try:
        inspect.signature(method).bind(*args, **kwargs)
    except TypeError as e:
        raise InvalidParams(str(e))

    try:
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result
    except (DeviceNotFound, ValueError) as e:
        raise InvalidParams(str(e))
    except UnitUnavailable as e:
        raise UnitUnavailableError(str(e))
    except Exception as e:
        # tornado_jsonrpc2 returned the message of the error to the client and did not log it
        logger.exception(f"RPC {request.method}: {e}")
        raise InternalError("internal") from None


class Handler(TokenAuth, JSONRPCHandler):
    """ JSON-RPC, the requests are authenticated by TokenAuth """

    # methods callable via JSON-RPC, other attributes of the handler are not exposed
    RPC_METHODS = frozenset((
        'input_get',
        'input_get_value',
        'input_set',
        'relay_get',
        'relay_set',
        'relay_set_for_time',
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

    def initialize(self, response_creator: Awaitable = None, version: Optional[str] = None):
        if response_creator is None:
            response_creator = functools.partial(create_response, backend=self)
        super().initialize(response_creator=response_creator, version=version)

    # ---- Input ----
    def input_get(self, circuit):
        inp = Devices.by_name(DI, circuit)
        state = inp.get()
        return state['value'], state['debounce']

    def input_get_value(self, circuit):
        inp = Devices.by_name(DI, circuit)
        return inp.get()['value']

    async def input_set(self, circuit, debounce):
        inp = Devices.by_name(DI, circuit)
        state, = await set_devices([(inp, dict(debounce=debounce))])
        return state

    # ---- Relay ----
    def relay_get(self, circuit):
        relay = Devices.by_name(RO, circuit)
        return relay.get()['value']

    async def relay_set(self, circuit, value):
        relay = Devices.by_name(RO, circuit)
        # to_bool() as in REST, the string "0" is off
        value = int(to_bool(value))
        await set_devices([(relay, dict(value=value))])
        return value

    async def relay_set_for_time(self, circuit, value, pulse_duration):
        relay = Devices.by_name(RO, circuit)
        state, = await set_devices([(relay, dict(value=value, pulse_duration=pulse_duration))])
        return state

    def output_get(self, circuit):
        relay = Devices.by_name(DO, circuit)
        state = relay.get()
        return state['value'], state['pending']

    async def output_set(self, circuit, value):
        relay = Devices.by_name(DO, circuit)
        value = int(to_bool(value))
        await set_devices([(relay, dict(value=value))])
        return value

    async def output_set_for_time(self, circuit, value, pulse_duration=None, timeout=None):
        """ timeout is a deprecated alias of pulse_duration """
        if (pulse_duration is None) == (timeout is None):
            raise ValueError('Exactly one of pulse_duration and its deprecated alias timeout is required')
        if pulse_duration is None:
            pulse_duration = timeout
        relay = Devices.by_name(DO, circuit)
        # pulse_duration is checked by the output, a positive finite number
        state, = await set_devices([(relay, dict(value=value, pulse_duration=pulse_duration))])
        return state

    # ---- Analog Input ----
    def ai_get(self, circuit):
        ai = Devices.by_name(AI, circuit)
        return ai.get()

    # ---- Analog Output (0-10V) ----
    async def ao_set_value(self, circuit, value):
        ao = Devices.by_name(AO, circuit)
        written = []

        async def operation():
            written.append(await ao.set_value(value))
        await ao.client.change(operation)
        return written[0]

    async def ao_set(self, circuit, value, mode):
        ao = Devices.by_name(AO, circuit)
        state, = await set_devices([(ao, dict(value=value, mode=mode))])
        return state

    # ---- OwBus (1wire bus) ----
    def owbus_get(self, circuit):
        ow = Devices.by_name(OWBUS, circuit)
        return ow.bus_driver.scan_interval

    async def owbus_set(self, circuit, scan_interval):
        ow = Devices.by_name(OWBUS, circuit)
        await ow.bus_driver.set(scan_interval=scan_interval)
        return ow.bus_driver.full()

    async def owbus_scan(self, circuit):
        ow = Devices.by_name(OWBUS, circuit)
        await ow.bus_driver.set(do_scan=True)
        return ow.bus_driver.full()

    def owbus_list(self, circuit):
        ow = Devices.by_name(OWBUS, circuit)
        return ow.bus_driver.list()

    # ---- Sensors (1wire thermo,humidity) ----
    async def sensor_set(self, circuit, interval):
        sens = Devices.by_name(SENSOR, circuit)
        await sens.set(interval=interval)
        return sens.full()

    def sensor_get(self, circuit):
        sens = Devices.by_name(SENSOR, circuit)
        return sens.get()

    def sensor_get_value(self, circuit):
        sens = Devices.by_name(SENSOR, circuit)
        return sens.get_value()
