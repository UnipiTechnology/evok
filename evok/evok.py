#!/usr/bin/python
import argparse
import asyncio
import contextlib

import os
import sys
import traceback
from importlib.metadata import version, PackageNotFoundError

import jsonschema
import tornado.httpserver
import tornado.httpclient
import tornado.ioloop
import tornado.web

import logging
from .log import logger

logging.basicConfig(level=logging.WARNING)  # noqa
logger.setLevel(logging.INFO)  # noqa

from operator import methodcaller
from tornado import escape
from .handlers_base import EvokWebHandlerBase, SCHEMA_VALIDATE, registered_devents
from urllib.parse import urlparse
from .schemas import schemas

from .handler_mqtt import MqttHandler
from .handler_rpc import RpcHandler
from .handler_webhook import WebhookHandler
from .handler_websocket import WebsocketHandler, websocket_config

import signal

import json
from . import config
from .devices import *

# from tornadows import complextypes

# Read config during initialisation
config_path = '/etc/evok'
if not os.path.isdir(config_path):
    config_path = os.path.dirname(os.path.realpath(__file__)) + '/evok'
    os.mkdir(config_path) if not os.path.exists(config_path) else None
evok_config = config.EvokConfig(config_path)
websocket_config.update(evok_config.get_api('websocket'))

try:
    evok_version = 'v' + version("evok")
except PackageNotFoundError:
    logger.error(f"Cannot detect evok version.")
    evok_version = 'unknown'

wh = None


class UserCookieHelper:
    _passwords = []

    def get_current_user(self):
        if len(self._passwords) == 0: return True
        return self.get_secure_cookie("user")


class LogoutHandler(tornado.web.RequestHandler):
    def get(self):
        self.clear_cookie("user")
        self.redirect(self.get_argument("next", "/"))


class LoginHandler(tornado.web.RequestHandler):
    def post(self):
        username = 'admin'
        password = self.get_argument("password", "")
        auth = self.check_permission(password, username)
        if auth:
            self.set_secure_cookie("user", escape.json_encode(username))
            self.redirect(self.get_argument("next", u"/"))
        else:
            error_msg = u"?error=" + tornado.escape.url_escape("Login incorrect")
            self.redirect(u"/auth/login/" + error_msg)

    def get(self):
        self.redirect(self.get_argument("next", u"/"))

    def check_permission(self, password, username=''):
        if username == "admin" and password in self._passwords:
            return True
        return False


class LegacyRestHandler(UserCookieHelper, EvokWebHandlerBase):
    def _get_kw(self) -> dict:
        return dict([(k, v[0].decode()) for (k, v) in self.request.body_arguments.items()])


class LegacyJsonHandler(UserCookieHelper, EvokWebHandlerBase):
    def _get_kw(self) -> dict:
        return json.loads(self.request.body)


class LoadAllHandler(UserCookieHelper, EvokWebHandlerBase):
    async def get(self):  # noqa
        """This function returns a heterogeneous list of all devices exposed via the REST API"""
        result = self._get_all()
        self.write(json.dumps(result))
        self.set_header('Content-Type', 'application/json')
        await self.finish()

    async def post(self):  # noqa
        pass


class VersionHandler(UserCookieHelper, tornado.web.RequestHandler):

    def initialize(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def get(self):
        self.write(evok_version)
        self.finish()


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
            if 'group_queries' in js_dict:
                for single_query in js_dict['group_queries']:
                    all_devs = []
                    for device_type in single_query['device_types']:
                        all_devs += Devices.by_name(device_type)
                    if 'group' in single_query:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.arm.major_group == single_query['group']:
                                all_devs_filtered.append(single_dev)
                        all_devs = all_devs_filtered
                    if 'device_circuits' in single_query:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.circuit in single_query['device_circuits']:
                                all_devs_filtered.append(single_dev)
                        all_devs = all_devs_filtered
                    if 'global_device_id' in single_query:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.dev_id == single_query['global_device_id']:
                                all_devs_filtered.append(single_dev)
                        all_devs = all_devs_filtered
                    if 'group_queries' in result:
                        result['group_queries'] += [map(methodcaller('full'), all_devs)]
                    else:
                        result['group_queries'] = [map(methodcaller('full'), all_devs)]
            if 'group_assignments' in js_dict:
                for single_command in js_dict['group_assignments']:
                    all_devs = Devices.by_name(single_command['device_type'])
                    if 'group' in single_command:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.arm.major_group == single_command['group']:
                                all_devs_filtered.append(single_dev)
                        all_devs = all_devs_filtered
                    if 'device_circuits' in single_command:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.circuit in single_command['device_circuits']:
                                all_devs_filtered.append(single_dev)
                        all_devs = all_devs_filtered
                    if 'global_device_id' in single_command:
                        all_devs_filtered = []
                        for single_dev in all_devs:
                            if single_dev.dev_id == single_command['global_device_id']:
                                all_devs_filtered.append(single_dev)
                        for single_dev in all_devs_filtered:
                            outp = await all_devs[single_dev].set(**(single_command['assigned_values']))
                    if 'group_assignments' in result:
                        result['group_assignments'] += [map(methodcaller('full'), all_devs)]
                    else:
                        result['group_assignments'] = [map(methodcaller('full'), all_devs)]
            if 'individual_assignments' in js_dict:
                for single_command in js_dict['individual_assignments']:
                    dev = single_command['device_type']
                    schema, example = schemas[dev]
                    outp = Devices.by_name(dev, circuit=single_command['device_circuit'])
                    kw = single_command['assigned_values']
                    if SCHEMA_VALIDATE:
                        jsonschema.validate(instance=kw, schema=schema)
                    outp = await outp.set(**kw)
                    if 'individual_assignments' in result:
                        result['individual_assignments'] += [outp]
                    else:
                        result['individual_assignments'] = [outp]
            self.write(json.dumps(result))
        except Exception as E:
            logger.error(f"Error while processing get: {str(type(E).__name__)}: {str(E)}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()
            self.write(json.dumps({'success': False, 'errors': {str(type(E).__name__): str(E)}}))
        finally:
            await self.finish()


class AliasTask:
    SAVE_TIME = 300  # s

    def __init__(self, aliases, loop):
        self.dirty_timestamp = 0
        self.dirty_trigger = asyncio.Event()
        self.save_trigger = asyncio.Event()
        self.aliases = aliases
        self.aliases.register_dirty_cb(lambda: self.dirty_trigger.set())
        self.aliases.register_save_cb(self.set_save_trigger)
        self.alias_task = None
        loop.add_callback(self.start)

    def set_save_trigger(self):
        if self.dirty_trigger.is_set():
            self.save_trigger.set()

    async def start(self):
        self.alias_task = asyncio.create_task(self.work())

    def cancel(self):
        self.alias_task.cancel()

    async def wait_for_save(self, timeout):
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.save_trigger.wait(), timeout)

    async def work(self):
        """ Wait for Event generated on setting alias and save aliases to file (in thread)"""
        self.save_trigger.clear()
        self.dirty_trigger.clear()
        while True:
            await self.dirty_trigger.wait()
            await self.wait_for_save(self.SAVE_TIME)
            try:
                self.save_trigger.clear()
                self.dirty_trigger.clear()
                alias_dict = self.aliases.get_dict_to_save()
                await asyncio.to_thread(config.save_aliases, alias_dict, '/var/lib/evok/alias.yaml')
            except Exception as E:
                logger.exception(E)


def status_cb(device, *kwargs):
    if "all" in registered_devents:
        for x in registered_devents['all']:
            x.on_event(device)


def config_cb(device, *kwargs):
    pass


################################ MAIN ################################

def main():
    arg_parser = argparse.ArgumentParser(prog='evok', description='')
    arg_parser.add_argument('-d', '--debug', action='store_true', default=False, help='Debug logging')
    arg_parser.add_argument('-v', '--version', action='store_true', default=False, help='Print evok version')

    args = arg_parser.parse_args()

    if args.version:
        print(evok_version)
        sys.exit(0)

    log_level = evok_config.logging.get("level", "INFO").upper()
    if args.debug:
        log_level = 'DEBUG'
    if log_level == 'DEBUG':
        # Debug level for pymodbus is too much!
        logging.getLogger('pymodbus').setLevel(logging.INFO)

    logger.info(f"Starting Evok {evok_version} using config directory '{config_path}'.")
    logger.info(f"Setting logging level to '{log_level}'.")

    logger.setLevel(log_level)
    logging.basicConfig(level=log_level)
    log_file = evok_config.logging.get("file", None)
    if log_file is not None:
        # rotating file handler
        filelog_handler = logging.handlers.TimedRotatingFileHandler(filename=log_file, when='D', backupCount=7)
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        filelog_handler.setFormatter(log_formatter)
        filelog_handler.setLevel(log_level)
        logger.addHandler(filelog_handler)
        # logging.getLogger('pymodbus').setLevel(logging.DEBUG)

    hw_dict = config.HWDict(dir_paths=[f'{config_path}/hw_definitions/'])
    config.load_aliases('/var/lib/evok/alias.yaml')
    address_api = evok_config.apis.get("address", None)

    port_api = evok_config.apis.get("port", 8080)

    api_routes = [
        (r"/rpc/?", RpcHandler),
        (r"/rest/all/?", LoadAllHandler),
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/bulk/?", JSONBulkHandler),
        (r"/json/all/?", LoadAllHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
        (r"/version/?", VersionHandler),
    ]

    if evok_config.get_api('websocket').get('enabled', False):
        api_routes.append((r"/ws/?", WebsocketHandler))

    app = tornado.web.Application(
        handlers=api_routes
    )

    #### prepare http server #####
    httpServerApi = tornado.httpserver.HTTPServer(app)
    httpServerApi.listen(port_api, address=address_api)
    logger.info(f"HTTP server API listening on {address_api}:{port_api}")

    webhook_config = evok_config.get_api('webhook')
    if webhook_config.get("enabled", False):
        wh_address = webhook_config.get("address", "http://127.0.0.1:80/index.html")
        wh_types = webhook_config.get("device_mask", ["di", "sensor", "watchdog"])
        wh_complex = webhook_config.get("complex_events", False)
        wh = WebhookHandler(wh_address, wh_types, wh_complex)
        wh.open()

    mainLoop = tornado.ioloop.IOLoop.instance()

    mqtt_config = evok_config.get_api('mqtt')
    if mqtt_config.get("enabled", False):
        mqtt_handler = MqttHandler(conf_data=mqtt_config, loop=mainLoop)
        mqtt_handler.start()

    #### prepare hardware according to config #####
    # prepare callbacks for config events
    devents.register_config_cb(config_cb)
    devents.register_status_cb(status_cb)

    # create hw devices
    config.create_devices(evok_config, hw_dict)
    Devices.register_device(RUN, Devices.aliases)

    alias_task = AliasTask(Devices.aliases, mainLoop)

    for bustype in [OWBUS]:
        for device in Devices.by_int(bustype):
            device.bus_driver.switch_to_async(mainLoop)

    for bustype in [TCPBUS, SERIALBUS]:
        for device in Devices.by_int(bustype):
            device.switch_to_async(mainLoop)

    for modbus_slave in Devices.by_int(MODBUS_SLAVE):
        modbus_slave.switch_to_async(mainLoop)
        if modbus_slave.scan_enabled:
            modbus_slave.start_scanning()

    def sig_handler(sig, frame):
        if sig in (signal.SIGTERM, signal.SIGINT):
            tornado.ioloop.IOLoop.instance().add_callback_from_signal(shutdown)

    # graceful shutdown
    def shutdown():
        alias_task.cancel()
        logger.info("Shutting down")
        tornado.ioloop.IOLoop.instance().stop()

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    mainLoop.start()


if __name__ == "__main__":
    main()
