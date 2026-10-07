#!/usr/bin/python
import argparse
import asyncio
import contextlib

import os
import sys
import traceback
from importlib.metadata import version, PackageNotFoundError

import tornado.httpserver
import tornado.httpclient
import tornado.web

import logging
import logging.handlers
from .log import logger, read_log_tail

from tornado import escape
from .handlers_base import EvokWebHandlerBase
from .bulk_handler import JSONBulkHandler
from .ws_handler import WsHandler, registered_ws

import signal

import json
from . import config
from .devices import MODBUS_SLAVE, RUN, OWBUS, TCPBUS, SERIALBUS
from .devices import Devices, devents
from . import rpc_handler

logging.basicConfig(level=logging.WARNING)
logger.setLevel(logging.INFO)

# from tornadows import complextypes

DEFAULT_CONFIG_DIR = '/etc/evok'
DEFAULT_ALIAS_FILE = '/var/lib/evok/alias.yaml'

# Set in main() after parsing command line arguments
config_path = None
alias_file = None
evok_config = None

try:
    evok_version = 'v' + version("evok")
except PackageNotFoundError:
    logger.error("Cannot detect evok version.")
    evok_version = 'unknown'

wh = None


class UserCookieHelper:
    _passwords = []

    def get_current_user(self):
        if len(self._passwords) == 0:
            return True
        return self.get_secure_cookie("user")


class WhHandler:
    def __init__(self, url, allowed_types, complex_events):
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.url = url
        self.allowed_types = allowed_types
        self.complex_events = complex_events

    def open(self):
        logger.debug(f"New WebHook connected {self.url}")
        if not ("all" in registered_ws):
            registered_ws["all"] = set()
        registered_ws["all"].add(self)

    def on_event(self, device):
        dev_all = device.full()
        outp = []
        for single_dev in dev_all:
            if single_dev['dev'] in self.allowed_types:
                outp += [single_dev]
        try:
            if len(outp) > 0:
                if not self.complex_events:
                    self.http_client.fetch(self.url, method="GET", headers={"Content-Type": "application/json"})
                else:
                    self.http_client.fetch(self.url, method="POST", headers={"Content-Type": "application/json"},
                                           body=json.dumps(outp))
        except Exception as E:
            logger.error(f"WhHandler error in event: {E}")
            if logger.level == logging.DEBUG:
                traceback.print_exc()


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


class LogHandler(UserCookieHelper, tornado.web.RequestHandler):
    """ GET /log?lines=N returns the last N lines of the log file as plain text """

    DEFAULT_LINES = 255
    MAX_LINES = 1000

    def initialize(self, log_file):
        self.log_file = log_file

    @tornado.web.authenticated
    async def get(self):
        if self.log_file is None:
            raise tornado.web.HTTPError(404, 'Logging to a file is not configured')
        try:
            lines = int(self.get_argument('lines', str(self.DEFAULT_LINES)))
        except ValueError:
            raise tornado.web.HTTPError(400, 'Invalid number of lines')
        lines = max(1, min(lines, self.MAX_LINES))
        text = await asyncio.to_thread(read_log_tail, self.log_file, lines)
        self.set_header('Content-Type', 'text/plain; charset=utf-8')
        self.write(text)


class AliasTask:
    SAVE_TIME = 300  # s

    def __init__(self, aliases, alias_file):
        self.alias_file = alias_file
        self.dirty_trigger = asyncio.Event()
        self.save_trigger = asyncio.Event()
        self.aliases = aliases
        self.aliases.register_dirty_cb(lambda: self.dirty_trigger.set())
        self.aliases.register_save_cb(self.set_save_trigger)
        self.alias_task = asyncio.create_task(self.work())

    def set_save_trigger(self):
        if self.dirty_trigger.is_set():
            self.save_trigger.set()

    def cancel(self):
        self.alias_task.cancel()

    async def wait_for_save(self, timeout):
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.save_trigger.wait(), timeout)

    def get_dict_to_save(self):
        self.save_trigger.clear()
        self.dirty_trigger.clear()
        return self.aliases.get_dict_to_save()

    async def work(self):
        """ Wait for Event generated on setting alias and save aliases to file (in thread)"""
        try:
            while True:
                await self.dirty_trigger.wait()
                await self.wait_for_save(self.SAVE_TIME)
                try:
                    alias_dict = self.get_dict_to_save()
                    await asyncio.to_thread(config.save_aliases, alias_dict, self.alias_file)
                except Exception as E:
                    logger.exception(E)
        except asyncio.CancelledError:
            # save pending changes on shutdown (synchronously, the task is being cancelled)
            if self.dirty_trigger.is_set():
                try:
                    config.save_aliases(self.get_dict_to_save(), self.alias_file)
                except Exception as E:
                    logger.exception(E)
            raise


def status_cb(device, *kwargs):
    if "all" in registered_ws:
        for x in registered_ws['all']:
            x.on_event(device)


def config_cb(device, *kwargs):
    pass


# ---- MAIN ----

async def main():
    global config_path, alias_file, evok_config

    arg_parser = argparse.ArgumentParser(prog='evok', description='')
    arg_parser.add_argument('-d', '--debug', action='store_true', default=False, help='Debug logging')
    arg_parser.add_argument('-v', '--version', action='store_true', default=False, help='Print evok version')
    arg_parser.add_argument('-c', '--config-dir',
                            default=os.environ.get('EVOK_CONFIG_DIR', DEFAULT_CONFIG_DIR),
                            help='Directory with config.yaml and hw_definitions/ '
                                 f'(env EVOK_CONFIG_DIR, default {DEFAULT_CONFIG_DIR})')
    arg_parser.add_argument('-a', '--alias-file',
                            default=os.environ.get('EVOK_ALIAS_FILE', DEFAULT_ALIAS_FILE),
                            help=f'File for storing aliases (env EVOK_ALIAS_FILE, default {DEFAULT_ALIAS_FILE})')

    args = arg_parser.parse_args()

    if args.version:
        print(evok_version)
        sys.exit(0)

    config_path = args.config_dir.rstrip('/') or '/'
    alias_file = args.alias_file
    if not os.path.isfile(os.path.join(config_path, 'config.yaml')):
        sys.exit(f"evok: config file '{os.path.join(config_path, 'config.yaml')}' not found "
                 "(use --config-dir or EVOK_CONFIG_DIR)")
    evok_config = config.EvokConfig(config_path)

    log_level = evok_config.logging.get("level", "INFO").upper()
    if args.debug:
        log_level = 'DEBUG'
#    if log_level == 'DEBUG':
        # Debug level for pymodbus is too much!
#        logging.getLogger('pymodbus').setLevel(logging.INFO)

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
    config.load_aliases(alias_file)
    address_api = evok_config.apis.get("address", None)

    port_api = evok_config.apis.get("port", 8080)

    api_routes = [
        (r"/rpc/?", rpc_handler.Handler),
        (r"/rest/all/?", LoadAllHandler),
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/bulk/?", JSONBulkHandler),
        (r"/json/all/?", LoadAllHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
        (r"/version/?", VersionHandler),
        (r"/log/?", LogHandler, dict(log_file=log_file)),
    ]

    if evok_config.get_api('websocket').get('enabled', False):
        all_filtered = evok_config.get_api('websocket').get("all_filtered", False)
        api_routes.append((r"/ws/?", WsHandler, dict(all_filtered=all_filtered)))

    app = tornado.web.Application(
        handlers=api_routes
    )

    # ---- prepare http server ----
    httpServerApi = tornado.httpserver.HTTPServer(app)
    httpServerApi.listen(port_api, address=address_api)
    logger.info(f"HTTP server API listening on {address_api}:{port_api}")

    webhook_config = evok_config.get_api('webhook')
    if webhook_config.get("enabled", False):
        wh_address = webhook_config.get("address", "http://127.0.0.1:80/index.html")
        wh_types = webhook_config.get("device_mask", ["di", "sensor", "watchdog"])
        wh_complex = webhook_config.get("complex_events", False)
        wh = WhHandler(wh_address, wh_types, wh_complex)
        wh.open()

    # ---- prepare hardware according to config ----
    # prepare callbacks for config events
    devents.register_config_cb(config_cb)
    devents.register_status_cb(status_cb)

    # create hw devices
    config.create_devices(evok_config, hw_dict)
    Devices.register_device(RUN, Devices.aliases)

    alias_task = AliasTask(Devices.aliases, alias_file)

    for bustype in [OWBUS]:
        for device in Devices.by_name(bustype):
            device.bus_driver.switch_to_async()

    for bustype in [TCPBUS, SERIALBUS]:
        for device in Devices.by_name(bustype):
            device.switch_to_async()

    for modbus_slave in Devices.by_name(MODBUS_SLAVE):
        if modbus_slave.scan_enabled:
            modbus_slave.start_scanning()

    # graceful shutdown: let main() return, so asyncio.run() can clean up
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutting down")
        alias_task.cancel()
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, shutdown)
    loop.add_signal_handler(signal.SIGINT, shutdown)

    await stop_event.wait()
    httpServerApi.stop()


def run():
    """Entry point of the evok console script and of python -m evok."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
