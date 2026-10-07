import json
from itertools import chain

from .schemas import schemas

import jsonschema
import tornado

from .devices import Devices
from .errors import DeviceNotFound
from .devices import OWBUS, DEVICE_INFO, SENSOR, MODBUS_SLAVE, \
    DI, DO, RO, AI, AO, OWPOWER, LED, WATCHDOG, \
    REGISTER, DATA_POINT
from .log import logger

SCHEMA_VALIDATE = True


class EvokWebHandlerBase(tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def _get_kw(self) -> dict:
        raise NotImplementedError("'_get_kw' not implemented!")

    # usage: GET /rest/DEVICE/CIRCUIT
    #        or
    #        GET /rest/DEVICE/CIRCUIT/PROPERTY
    @tornado.web.authenticated
    def get(self, dev, circuit, prop):

        def one_device(device, prop):
            result = device.full()
            if not prop:
                return result
            if prop not in result:
                raise DeviceNotFound(f'Invalid property name {prop}')
            return {prop: result[prop]}

        try:
            if circuit == 'all':
                result = [{'circuit': d.circuit, **one_device(d, prop)} for d in Devices.by_name(dev)]
            else:
                device = Devices.by_name(dev, circuit)
                result = one_device(device, prop)

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
        try:
            device = Devices.by_name(dev, circuit)
            kw = self._get_kw()
            if SCHEMA_VALIDATE:
                if dev not in schemas:
                    raise ValueError(f'Invalid device name {dev}')
                schema, example = schemas[dev]
                jsonschema.validate(instance=kw, schema=schema)
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
        devtypes = (DI, RO, DO, AI, AO, SENSOR, LED, WATCHDOG, MODBUS_SLAVE, OWPOWER,
                    REGISTER, DATA_POINT, OWBUS, DEVICE_INFO)
        devices = chain.from_iterable(Devices.by_name(devtype) for devtype in devtypes)
        return [dev.full() for dev in devices]

    def options(self):
        self.set_status(204)
        self.finish()
