import json
from operator import methodcaller

import jsonschema
import tornado.web

from .devices import Devices
from .errors import DeviceNotFound
from .handlers_base import SCHEMA_VALIDATE
from .log import logger
from .schemas import schemas, bulk_post_inp_schema


class JSONBulkHandler(tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Content-Type", "application/json")
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def options(self):
        # no body
        self.set_status(204)
        self.finish()

    async def post(self):
        """This function returns a heterogeneous list of all devices exposed via the REST API"""
        result = {}
        try:
            js_dict = json.loads(self.request.body)
            # the structure of the request, the assigned values are checked by the device schemas
            jsonschema.validate(instance=js_dict, schema=bulk_post_inp_schema)
            if 'group_queries' in js_dict:
                result['group_queries'] = []
                for single_query in js_dict['group_queries']:
                    all_devs = [dev for device_type in single_query['device_types']
                                for dev in Devices.by_name(device_type)]
                    if (grp := single_query.get('group', None)) is not None:
                        all_devs = [dev for dev in all_devs if dev.major_group == str(grp)]
                    if (circuits := single_query.get('device_circuits', None)) is not None:
                        all_devs = [dev for dev in all_devs if dev.circuit in circuits]
                    result['group_queries'].append(list(map(methodcaller('full'), all_devs)))

            if 'group_assignments' in js_dict:
                result['group_assignments'] = []
                for single_command in js_dict['group_assignments']:
                    dev_type = single_command['device_type']
                    kw = single_command['assigned_values']
                    all_devs = Devices.by_name(dev_type)
                    if SCHEMA_VALIDATE:
                        # validate before setting any device of the group
                        if dev_type not in schemas:
                            raise ValueError(f'Invalid device name {dev_type}')
                        jsonschema.validate(instance=kw, schema=schemas[dev_type][0])
                    if (grp := single_command.get('group', None)) is not None:
                        all_devs = [dev for dev in all_devs if dev.major_group == str(grp)]
                    if (circuits := single_command.get('device_circuits', None)) is not None:
                        all_devs = [dev for dev in all_devs if dev.circuit in circuits]
                    for dev in all_devs:
                        await dev.set(**kw)
                    result['group_assignments'].append(list(map(methodcaller('full'), all_devs)))

            if 'individual_assignments' in js_dict:
                result['individual_assignments'] = []
                for single_command in js_dict['individual_assignments']:
                    dev_type = single_command['device_type']
                    kw = single_command['assigned_values']
                    dev = Devices.by_name(dev_type, circuit=single_command['device_circuit'])
                    if SCHEMA_VALIDATE:
                        if dev_type not in schemas:
                            raise ValueError(f'Invalid device name {dev_type}')
                        jsonschema.validate(instance=kw, schema=schemas[dev_type][0])
                    await dev.set(**kw)
                    result['individual_assignments'].append(dev.full())

            self.write(json.dumps(result))
        except (ValueError, DeviceNotFound, jsonschema.ValidationError) as E:
            # the string of a ValidationError contains the whole schema
            message = E.message if isinstance(E, jsonschema.ValidationError) else str(E)
            logger.error(f"BULK: {message}")
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): message}}))
            # a wrong device is not found, wrong data is a bad request
            self.set_status(status_code=404 if isinstance(E, DeviceNotFound) else 400)
        except Exception as E:
            logger.exception(f"BULK: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {'Server error': 'internal'}}))
            self.set_status(status_code=500)
        finally:
            await self.finish()
