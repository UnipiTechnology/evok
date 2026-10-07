import json
from itertools import chain

import jsonschema
import tornado.web

from .devices import Devices
from .devices import OWBUS, DEVICE_INFO, SENSOR, MODBUS_SLAVE, \
    DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
    REGISTER, DATA_POINT, NV_SAVE
from .errors import DeviceNotFound
from .log import logger
from .schemas import schemas

SCHEMA_VALIDATE = True


class EvokWebHandlerBase(tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def _get_kw(self) -> dict:
        raise NotImplementedError("'_get_kw' not implemented!")

    @tornado.web.authenticated
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

            An unknown device or circuit is 404, invalid params 400, other errors 500.
        """
        try:
            # .../alias is the documented URL for setting the alias, the params are in the body
            if prop not in (None, 'alias'):
                raise DeviceNotFound(f"Invalid URL, POST sets the params of the device in the body, not '{prop}'")
            if circuit == 'all':
                raise DeviceNotFound("POST cannot set all devices, use the bulk API")
            device = Devices.by_name(dev, circuit)
            kw = self._get_kw()
            if SCHEMA_VALIDATE:
                if dev not in schemas:
                    raise ValueError(f'Invalid device name {dev}')
                jsonschema.validate(instance=kw, schema=schemas[dev][0])
            await device.set(**kw)
            self.write(json.dumps({'success': True, 'result': device.full()}))
        except (ValueError, DeviceNotFound, jsonschema.ValidationError) as E:
            # the string of a ValidationError contains the whole schema
            message = E.message if isinstance(E, jsonschema.ValidationError) else str(E)
            logger.error(f"POST: {message}")
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): message}}))
            # a wrong URL is not found, wrong data is a bad request
            self.set_status(status_code=404 if isinstance(E, DeviceNotFound) else 400)

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
