import json
from itertools import chain

import jsonschema
import tornado.web

from .devices import Devices, to_float
from .devices import OWBUS, DEVICE_INFO, SENSOR, MODBUS_SLAVE, \
    DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
    REGISTER, DATA_POINT, NV_SAVE
from .auth import TokenAuth
from .errors import DeviceNotFound, UnitUnavailable
from .log import logger
from .modbus import set_devices
from .schemas import schemas

SCHEMA_VALIDATE = True

# errors of a request, reported to the client, other errors are internal
CLIENT_ERRORS = (ValueError, DeviceNotFound, UnitUnavailable, jsonschema.ValidationError)


def check_params(dev_type, kw):
    """ Validate the params of set() by the schema of the device type, used by REST, bulk and WebSocket """
    if SCHEMA_VALIDATE:
        if dev_type not in schemas:
            raise ValueError(f'Invalid device name {dev_type}')
        schema = schemas[dev_type][0]
        jsonschema.validate(instance=kw, schema=schema)
        _check_numbers(schema, kw)


def _check_numbers(schema, kw):
    """ jsonschema checks the range of numbers only, a form sends strings; NaN and infinity pass any range """
    for name, value in kw.items():
        rules = schema['properties'].get(name, {})
        types = rules.get('type', [])
        if 'number' not in types or isinstance(value, bool):
            continue
        if isinstance(value, str):
            try:
                float(value)
            except ValueError:
                continue    # not a number, rejected by the device
        number = to_float(value)
        if 'minimum' in rules and number < rules['minimum']:
            raise ValueError(f"{name} {value} is less than the minimum {rules['minimum']}")
        if 'maximum' in rules and number > rules['maximum']:
            raise ValueError(f"{name} {value} is greater than the maximum {rules['maximum']}")


def client_error(error) -> tuple[dict, int]:
    """ The errors reported to the client and the HTTP status of one of CLIENT_ERRORS """
    # the string of a ValidationError contains the whole schema
    message = error.message if isinstance(error, jsonschema.ValidationError) else str(error)
    # a wrong device is not found, an unavailable Modbus unit cannot be changed now, wrong data is a bad request
    if isinstance(error, DeviceNotFound):
        status = 404
    elif isinstance(error, UnitUnavailable):
        status = 503
    else:
        status = 400
    return {type(error).__name__: message}, status


class EvokWebHandlerBase(TokenAuth, tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def _get_kw(self) -> dict:
        raise NotImplementedError("'_get_kw' not implemented!")

    def get(self, dev, circuit, prop):
        """ GET /rest/DEVICE/CIRCUIT             the state of the device
            GET /rest/DEVICE/CIRCUIT/PROPERTY    a property of the state
            GET /rest/DEVICE/all[/PROPERTY]      the states (properties) of all devices of the type

            An unknown device, circuit or property is 404, other errors 500.
        """
        try:
            if circuit == 'all' and prop:
                # the devices without the property are skipped, e.g. 'range' of AI in some modes
                states = [d.full() for d in Devices.by_name(dev)]
                result = [{'circuit': state['circuit'], prop: state[prop]} for state in states if prop in state]
                if states and not result:
                    raise DeviceNotFound(f'Invalid property name {prop}')
            elif circuit == 'all':
                result = [d.full() for d in Devices.by_name(dev)]
            else:
                result = Devices.by_name(dev, circuit).full()
                if prop:
                    if prop not in result:
                        raise DeviceNotFound(f'Invalid property name {prop}')
                    result = {prop: result[prop]}

            self.write(json.dumps(result))
        except DeviceNotFound as E:
            logger.error(f"GET: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): str(E)}}))
            self.set_status(status_code=404)

        except Exception as E:
            logger.exception(f"GET: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {'Server error': 'internal'}}))
            self.set_status(status_code=500)
        self.set_header('Content-Type', 'application/json')
        self.finish()

    async def post(self, dev, circuit, prop):
        """ POST /rest/DEVICE/CIRCUIT[/alias] sets the params of the device in the body, validated by its schema

            An unknown device or circuit is 404, invalid params 400, an unavailable Modbus unit 503,
            other errors 500.
        """
        try:
            # .../alias is the documented URL for setting the alias, the params are in the body
            if prop not in (None, 'alias'):
                raise DeviceNotFound(f"Invalid URL, POST sets the params of the device in the body, not '{prop}'")
            if circuit == 'all':
                raise DeviceNotFound("POST cannot set all devices, use the bulk API")
            device = Devices.by_name(dev, circuit)
            kw = self._get_kw()
            check_params(dev, kw)
            state, = await set_devices([(device, kw)])
            self.write(json.dumps({'success': True, 'result': state}))
        except CLIENT_ERRORS as E:
            errors, status = client_error(E)
            logger.error(f"POST: {errors}")
            self.write(json.dumps({'success': False, 'errors': errors}))
            self.set_status(status_code=status)

        except Exception as E:
            logger.exception(f"POST: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {'Server error': 'internal'}}))
            self.set_status(status_code=500)
        self.set_header('Content-Type', 'application/json')
        await self.finish()

    def _get_all(self):
        devtypes = (DI, RO, DO, AI, AO, SENSOR, LED, WATCHDOG, MODBUS_SLAVE, OWPOWER, NV_SAVE,
                    REGISTER, DATA_POINT, OWBUS, DEVICE_INFO)
        devices = chain.from_iterable(Devices.by_name(devtype) for devtype in devtypes)
        return [dev.full() for dev in devices]

    def options(self):
        self.set_status(204)
        self.finish()
