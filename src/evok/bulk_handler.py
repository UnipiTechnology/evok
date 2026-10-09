import json

import jsonschema
import tornado.web

from .auth import TokenAuth
from .devices import Devices, devtype_of
from .handlers_base import CLIENT_ERRORS, check_params, client_error
from .modbus import set_devices
from .log import logger
from .schemas import bulk_post_inp_schema


class JSONBulkHandler(TokenAuth, tornado.web.RequestHandler):
    def initialize(self):
        self.set_header("Content-Type", "application/json")
        # GET is not supported, the request is in the body of POST
        self.set_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

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
            # a circuit or an alias, as in individual_assignments
            devices = [dev for dev in devices
                       if dev.circuit in circuits or (getattr(dev, 'alias', '') and dev.alias in circuits)]
        return list(devices)

    async def post(self):
        """ Query and set several devices in one request

            All assignments are checked before any device is set. The assignments are done by the Modbus
            units, the devices of a unit are set together under its lock and then read, the units one
            after another in the order of their first assignment. An error while setting a device returns
            the results of the units done so far, of its unit the assignments before it, together with the error.
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
                check_params(command['device_type'], command['assigned_values'])
                group_assignments.append((devices, command['assigned_values']))
            individual_assignments = []
            for command in js_dict.get('individual_assignments', []):
                dev = Devices.by_name(command['device_type'], circuit=command['device_circuit'])
                check_params(command['device_type'], command['assigned_values'])
                individual_assignments.append((dev, command['assigned_values']))

            if 'group_queries' in js_dict:
                result['group_queries'] = []
                for query in js_dict['group_queries']:
                    # altnames of the same type, e.g. 'di' and 'input', return its devices once
                    devtypes = dict.fromkeys(devtype_of(device_type) for device_type in query['device_types'])
                    devices = [dev for devtype in devtypes for dev in Devices.by_name(devtype)]
                    result['group_queries'].append([dev.full() for dev in self._filter(devices, query)])

            # all assignments in the order of the request, with their place in the result
            assignments, places = [], []
            for command, (devices, kw) in enumerate(group_assignments):
                for dev in devices:
                    assignments.append((dev, kw))
                    places.append(('group_assignments', command))
            for dev, kw in individual_assignments:
                assignments.append((dev, kw))
                places.append(('individual_assignments', None))
            states = {}
            try:
                await set_devices(assignments, states)
            finally:
                # the results in the order of the request, also of the assignments done before an error
                if 'group_assignments' in js_dict:
                    result['group_assignments'] = [[] for _ in group_assignments]
                if 'individual_assignments' in js_dict:
                    result['individual_assignments'] = []
                for index in sorted(states):
                    section, command = places[index]
                    if command is None:
                        result[section].append(states[index])
                    else:
                        result[section][command].append(states[index])

            self.write(json.dumps(result))
        except CLIENT_ERRORS as E:
            errors, status = client_error(E)
            logger.error(f"BULK: {errors}")
            # the results of the commands done before the error
            self.write(json.dumps({'success': False, 'errors': errors, **result}))
            self.set_status(status_code=status)
        except Exception as E:
            logger.exception(f"BULK: {str(E)}")
            self.write(json.dumps({'success': False, 'errors': {'Server error': 'internal'}, **result}))
            self.set_status(status_code=500)
        finally:
            await self.finish()
