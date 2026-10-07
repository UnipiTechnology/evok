import json

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

    @staticmethod
    def _filter(devices, command) -> list:
        """ The devices of the optional group and circuits of the command """
        if (grp := command.get('group')) is not None:
            # major_group is a string of Modbus devices and a number of 1-Wire ones, some devices have none
            devices = [dev for dev in devices if str(getattr(dev, 'major_group', None)) == str(grp)]
        if (circuits := command.get('device_circuits')) is not None:
            devices = [dev for dev in devices if dev.circuit in circuits]
        return list(devices)

    @staticmethod
    def _check_params(dev_type, kw):
        if SCHEMA_VALIDATE:
            if dev_type not in schemas:
                raise ValueError(f'Invalid device name {dev_type}')
            jsonschema.validate(instance=kw, schema=schemas[dev_type][0])

    async def post(self):
        """ Query and set several devices in one request

            All assignments are checked before any device is set. An error while setting a device
            returns the results of the commands done so far together with the error.
        """
        result = {}
        try:
            js_dict = json.loads(self.request.body)
            # the structure of the request, the assigned values are checked by the device schemas
            jsonschema.validate(instance=js_dict, schema=bulk_post_inp_schema)

            # find the devices and check the values of all assignments before setting any device
            group_assignments = []
            for command in js_dict.get('group_assignments', []):
                devices = self._filter(Devices.by_name(command['device_type']), command)
                self._check_params(command['device_type'], command['assigned_values'])
                group_assignments.append((devices, command['assigned_values']))
            individual_assignments = []
            for command in js_dict.get('individual_assignments', []):
                dev = Devices.by_name(command['device_type'], circuit=command['device_circuit'])
                self._check_params(command['device_type'], command['assigned_values'])
                individual_assignments.append((dev, command['assigned_values']))

            if 'group_queries' in js_dict:
                result['group_queries'] = []
                for query in js_dict['group_queries']:
                    devices = [dev for device_type in query['device_types'] for dev in Devices.by_name(device_type)]
                    result['group_queries'].append([dev.full() for dev in self._filter(devices, query)])

            if 'group_assignments' in js_dict:
                result['group_assignments'] = []
                for devices, kw in group_assignments:
                    states = []
                    result['group_assignments'].append(states)
                    for dev in devices:
                        await dev.set(**kw)
                        states.append(dev.full())

            if 'individual_assignments' in js_dict:
                result['individual_assignments'] = []
                for dev, kw in individual_assignments:
                    await dev.set(**kw)
                    result['individual_assignments'].append(dev.full())

            self.write(json.dumps(result))
        except (ValueError, DeviceNotFound, jsonschema.ValidationError) as E:
            # the string of a ValidationError contains the whole schema
            message = E.message if isinstance(E, jsonschema.ValidationError) else str(E)
            logger.error(f"BULK: {message}")
            # the results of the commands done before the error
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): message}, **result}))
            # a wrong device is not found, wrong data is a bad request
            self.set_status(status_code=404 if isinstance(E, DeviceNotFound) else 400)
        except Exception as E:
            logger.exception(f"BULK: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {'Server error': 'internal'}, **result}))
            self.set_status(status_code=500)
        finally:
            await self.finish()
