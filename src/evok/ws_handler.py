import json
import logging
import traceback
from urllib.parse import urlparse

from tornado import websocket

from .devices import DI, RO, AI, AO, SENSOR
from .devices import Devices, devtype_altnames, num_to_devtype_name
from .log import logger

# clients notified by status_cb() in evok.py, websocket clients and the webhook
registered_ws = {}


class WsHandler(websocket.WebSocketHandler):

    def initialize(self, all_filtered=False):
        self.all_filtered = all_filtered

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
        if not ("all" in registered_ws):
            registered_ws["all"] = set()
        registered_ws["all"].add(self)

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
            except Exception:
                cmd = None
            # get FULL state of each IO
            if cmd == "all":
                result = []
                devices = [DI, RO, AI, AO, SENSOR]
                if self.all_filtered:
                    if len(self.filter) == 1 and self.filter[0] == "default":
                        for dev_name in devices:
                            result += map(lambda dev: dev.full(), Devices.by_int(dev_name))
                    else:
                        for dev_name in num_to_devtype_name.values():
                            added_results = map(lambda dev: dev.full() if hasattr(dev, "full") else None,
                                                Devices.by_int(dev_name))
                            for added_result in added_results:
                                if added_result is not None and added_result in self.filter:
                                    result.append(added_result)
                else:
                    for dev_name in num_to_devtype_name.values():
                        added_results = map(lambda dev: dev.full() if hasattr(dev, "full") else None,
                                            Devices.by_int(dev_name))
                        for added_result in added_results:
                            if added_result is not None:
                                result.append(added_result)
                await self.write_message(json.dumps(result))
            # set device state
            elif cmd == "filter":
                devices = []
                try:
                    for single_dev in message["devices"]:
                        if (str(single_dev) in num_to_devtype_name.values()) or (str(single_dev) in devtype_altnames):
                            devices += [single_dev]
                    if len(devices) > 0 or len(message["devices"]) == 0:
                        self.filter = devices
                        if len(message["devices"]) and message["devices"][0] == "default":
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
                except Exception:
                    value = None
                try:
                    device = Devices.by_name(dev, circuit)
                    if cmd == "full":
                        # full() is not a coroutine, send the state only to the requesting client
                        await self.write_message(json.dumps(device.full()))
                    else:
                        func = getattr(device, cmd)
                        if value is not None:
                            if type(value) == dict:
                                await func(**value)
                            else:
                                await func(value)
                        else:
                            # Set other property than "value" (e.g. counter of an input)
                            funcdata = {key: value for (key, value) in message.items() if
                                        key not in ("circuit", "value", "cmd", "dev")}
                            if len(funcdata) > 0:
                                await func(**funcdata)
                            else:
                                await func()
                # nebo except Exception as e:
                except Exception as E:
                    logger.error(f"EsHandler error in request: {E}")
                    if logger.level == logging.DEBUG:
                        traceback.print_exc()

        except Exception as E:
            logger.debug("Skipping WS message: %s (%s)", message, str(E))
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            # skip it since we do not understand this message....
            pass

    def on_close(self):
        if ("all" in registered_ws) and (self in registered_ws["all"]):
            registered_ws["all"].remove(self)
