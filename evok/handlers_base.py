import json
import logging
import traceback

from .schemas import schemas

import jsonschema
import tornado

from .devices import *
from .log import logger

SCHEMA_VALIDATE = True

registered_devents = {}


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
        try:
            if prop:
                if prop[0] in ('_',):
                    raise Exception('Invalid property name')
            if circuit == 'all':
                if prop:
                    result = list(map(lambda d: {'circuit': d.circuit, prop: getattr(d, prop)},
                                      Devices.by_name(dev)))
                else:
                    result = list(map(lambda d: d.full(), Devices.by_name(dev)))
            else:
                device = Devices.by_name(dev, circuit)
                if prop:
                    result = {prop: getattr(device, prop)}
                else:
                    result = device.full()
            self.write(json.dumps(result))
        except Exception as E:
            logger.error(f"Error while processing get: {str(type(E).__name__)}: {str(E)}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): str(E)}}))
            self.set_status(status_code=404)
        self.set_header('Content-Type', 'application/json')
        self.finish()

    async def post(self, dev, circuit, prop):
        try:
            device = Devices.by_name(dev, circuit)
            kw = self._get_kw()
            if SCHEMA_VALIDATE and dev in schemas:
                schema, example = schemas[dev]
                jsonschema.validate(instance=kw, schema=schema)
            result = await device.set(**kw)
            self.write(json.dumps({'success': True, 'result': result}))
        except Exception as E:
            logger.error(f"Error while processing post: {str(type(E).__name__)}: {str(E)}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): str(E)}}))
            self.set_status(status_code=404)
        self.set_header('Content-Type', 'application/json')
        await self.finish()

    def _get_all(self):
        result = list(map(lambda dev: dev.full(), Devices.by_int(DI)))
        result += map(lambda dev: dev.full(), Devices.by_int(RO))
        result += map(lambda dev: dev.full(), Devices.by_int(DO))
        result += map(lambda dev: dev.full(), Devices.by_int(AI))
        result += map(lambda dev: dev.full(), Devices.by_int(AO))
        result += map(lambda dev: dev.full(), Devices.by_int(SENSOR))
        result += map(lambda dev: dev.full(), Devices.by_int(LED))
        result += map(lambda dev: dev.full(), Devices.by_int(WATCHDOG))
        result += map(lambda dev: dev.full(), Devices.by_int(MODBUS_SLAVE))
        result += map(lambda dev: dev.full(), Devices.by_int(OWPOWER))
        result += map(lambda dev: dev.full(), Devices.by_int(REGISTER))
        result += map(lambda dev: dev.full(), Devices.by_int(DATA_POINT))
        result += map(lambda dev: dev.full(), Devices.by_int(OWBUS))
        result += map(lambda dev: dev.full(), Devices.by_int(DEVICE_INFO))
        return result

    def options(self):
        self.set_status(204)
        self.finish()
