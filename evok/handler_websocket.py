import json
import logging
import traceback
from tornado import websocket
from .devices import *
from urllib.parse import urlparse

from .handlers_base import registered_devents

websocket_config = {}
# TODO: some better solution


class WebsocketHandler(websocket.WebSocketHandler):

    def check_origin(self, origin):
        # fix issue when Node-RED removes the 'prefix://'
        parsed_origin = urlparse(origin)
        origin = parsed_origin.netloc
        origin = origin.lower()
        # return origin == host or origin_origin == host
        return True

    def open(self):
        self.filter = ["default"]
        logger.debug("New WebSocket client connected")
        if not ("all" in registered_devents):
            registered_devents["all"] = set()
        registered_devents["all"].add(self)

    def on_event(self, device):
        outp = []
        try:
            if len(self.filter) == 1 and self.filter[0] == "default":
                self.write_message(json.dumps(device.full()))
            else:
                dev_all = device.full()
                if 'dev' in dev_all:
                    dev_all = [dev_all]
                for single_dev in dev_all:
                    if single_dev['dev'] in self.filter:
                        outp += [single_dev]
                if len(outp) > 0:
                    self.write_message(json.dumps(outp))
        except Exception as E:
            logger.error(f"WsHandler error in event: {E}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()

    async def on_message(self, message):
        try:
            message = json.loads(message)
            try:
                cmd = message["cmd"]
            except:
                cmd = None
            # get FULL state of each IO
            if cmd == "all":
                result = []
                devices = [DI, RO, AI, AO, SENSOR]
                if websocket_config.get("all_filtered", False):
                    if (len(self.filter) == 1 and self.filter[0] == "default"):
                        for dev in devices:
                            result += map(lambda dev: dev.full(), Devices.by_int(dev))
                    else:
                        for dev in range(0, 25):
                            added_results = map(lambda dev: dev.full() if dev.full() is not None else '',
                                                Devices.by_int(dev))
                            for added_result in added_results:
                                if added_result != '' and added_result['dev'] in self.filter:
                                    result.append(added_result)
                else:
                    for dev in range(0, 25):
                        added_results = map(lambda dev: dev.full() if dev.full() is not None else '',
                                            Devices.by_int(dev))
                        for added_result in added_results:
                            if added_result != '':
                                result.append(added_result)
                await self.write_message(json.dumps(result))
            # set device state
            elif cmd == "filter":
                devices = []
                try:
                    for single_dev in message["devices"]:
                        if (str(single_dev) in devtype_names) or (str(single_dev) in devtype_altnames):
                            devices += [single_dev]
                    if len(devices) > 0 or len(message["devices"]) == 0:
                        self.filter = devices
                        if message["devices"][0] == "default":
                            self.filter = ["default"]
                    else:
                        raise Exception("Invalid 'devices' argument: %s" % str(message["devices"]))
                except Exception as E:
                    logger.exception("Exc: %s", str(E))
            elif cmd is not None:
                dev = message["dev"]
                circuit = message["circuit"]
                try:
                    value = message["value"]
                except:
                    value = None
                try:
                    device = Devices.by_name(dev, circuit)
                    func = getattr(device, cmd)
                    if value is not None:
                        if type(value) == dict:
                            result = await func(**value)
                        else:
                            result = await func(value)
                    else:
                        # Set other property than "value" (e.g. counter of an input)
                        funcdata = {key: value for (key, value) in message.items() if
                                    key not in ("circuit", "value", "cmd", "dev")}
                        if len(funcdata) > 0:
                            result = await func(**funcdata)
                        else:
                            result = await func()
                    if cmd == "full":
                        await self.write_message(json.dumps(result))
                    # send response only to the modbusclient_rs485 requesting full info
                # nebo except Exception as e:
                except Exception as E:
                    logger.error(f"EsHandler error in request: {E}")
                    if logger.level == logging.DEBUG:
                        traceback.print_exc()

        except Exception as E:
            logger.debug("Skipping WS message: %s (%s)", message, str(E))
            # skip it since we do not understand this message....
            pass

    def on_close(self):
        if ("all" in registered_devents) and (self in registered_devents["all"]):
            registered_devents["all"].remove(self)
            if len(registered_devents["all"]) == 0:
                for neuron in Devices.by_int(MODBUS_SLAVE):
                    neuron.stop_scanning()
