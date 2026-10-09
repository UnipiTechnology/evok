import argparse
import asyncio
import contextlib
import json
import logging
import logging.handlers
import os
import signal
import sys
from importlib.metadata import version, PackageNotFoundError

import tornado.httpclient
import tornado.httpserver
import tornado.web

from . import auth
from . import config
from . import rpc_handler
from .auth import TokenAuth
from .bulk_handler import JSONBulkHandler
from .devices import MODBUS_SLAVE, RUN, OWBUS
from .devices import Devices, devents, devtype_of
from .handlers_base import EvokWebHandlerBase
from .log import logger, read_log_tail
from .modbus.digital import finish_pulses
from .ws_handler import WEBSOCKET_SETTINGS, WsHandler, registered_ws

logging.basicConfig(level=logging.WARNING)
logger.setLevel(logging.INFO)

DEFAULT_CONFIG_DIR = '/etc/evok'
MAX_BODY_SIZE = 1024 * 1024     # a body of a request of the API, a bulk of hundreds of assignments has tens of kB
DEFAULT_ALIAS_FILE = '/var/lib/evok/alias.yaml'

try:
    evok_version = 'v' + version("evok")
except PackageNotFoundError:
    logger.error("Cannot detect evok version.")
    evok_version = 'unknown'


class WhHandler:
    """ Notifies the webhook about the changed devices

        At most one request is sent per min_interval seconds and only one request at a time.
        The changes in the meantime are merged, only the last state of each device is sent.
    """

    def __init__(self, url, allowed_types, complex_events, min_interval=1.0):
        self.http_client = tornado.httpclient.AsyncHTTPClient()
        self.url = url
        # altnames as 'wd' are converted to the device types
        self.allowed_types = [devtype_of(str(name)) for name in allowed_types]
        self.complex_events = complex_events
        self.min_interval = float(min_interval)
        self.pending: dict[tuple, dict] = {}    # the last state of each changed device
        self.last_sent = None                   # loop time of the last request
        self.send_task: asyncio.Task | None = None

    def open(self):
        logger.debug(f"New WebHook connected {self.url}")
        if not ("all" in registered_ws):
            registered_ws["all"] = set()
        registered_ws["all"].add(self)

    def on_event(self, device):
        """ Queue the changed devices of the allowed types for the next request

            A change of Modbus devices comes as a Proxy with a list of states,
            a change of a 1-Wire sensor as the sensor with its state.
        """
        try:
            states = device.full()
            if isinstance(states, dict):
                states = [states]
            for state in states:
                if devtype_of(state['dev']) in self.allowed_types:
                    self.pending[(state['dev'], state.get('circuit'))] = state
            if self.pending and self.send_task is None:
                self.send_task = asyncio.create_task(self._send())
        except Exception as E:
            logger.exception(f"WhHandler error in event: {E}")

    async def _send(self):
        """ Send the pending states, wait min_interval since the last request """
        loop = asyncio.get_running_loop()
        try:
            while self.pending:
                if self.last_sent is not None:
                    await asyncio.sleep(max(0.0, self.last_sent + self.min_interval - loop.time()))
                states = list(self.pending.values())
                self.pending.clear()
                self.last_sent = loop.time()
                try:
                    if not self.complex_events:
                        await self.http_client.fetch(self.url, method="GET",
                                                     headers={"Content-Type": "application/json"})
                    else:
                        await self.http_client.fetch(self.url, method="POST",
                                                     headers={"Content-Type": "application/json"},
                                                     body=json.dumps(states))
                except Exception as E:
                    # the states are not sent again, the next change is sent
                    logger.error(f"WhHandler error in request to {self.url}: {E}")
        finally:
            self.send_task = None


class LegacyRestHandler(EvokWebHandlerBase):
    def _get_kw(self) -> dict:
        return dict([(k, v[0].decode()) for (k, v) in self.request.body_arguments.items()])


class LegacyJsonHandler(EvokWebHandlerBase):
    def _get_kw(self) -> dict:
        return json.loads(self.request.body)


class LoadAllHandler(EvokWebHandlerBase):
    # tornado returns 405 Method Not Allowed for POST
    SUPPORTED_METHODS = ("GET", "OPTIONS")

    async def get(self):  # noqa
        """This function returns a heterogeneous list of all devices exposed via the REST API"""
        result = self._get_all()
        self.write(json.dumps(result))
        self.set_header('Content-Type', 'application/json')
        await self.finish()


class VersionHandler(TokenAuth, tornado.web.RequestHandler):

    auth_exempt = True      # for monitoring, it tells only the version

    def initialize(self):
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')

    def get(self):
        self.write(evok_version)
        self.finish()


class LogHandler(TokenAuth, tornado.web.RequestHandler):
    """ GET /log?lines=N returns the last N lines of the log file as plain text """

    DEFAULT_LINES = 255
    MAX_LINES = 1000

    def initialize(self, log_file):
        self.log_file = log_file

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
                    # try it again after SAVE_TIME
                    self.dirty_trigger.set()
        except asyncio.CancelledError:
            # save pending changes on shutdown (synchronously, the task is being cancelled)
            if self.dirty_trigger.is_set():
                try:
                    config.save_aliases(self.get_dict_to_save(), self.alias_file)
                except Exception as E:
                    logger.exception(E)
            raise


def status_cb(device, *args):
    # a copy, a client could be removed while the event is sent
    for x in list(registered_ws.get('all', ())):
        x.on_event(device)


# ---- MAIN ----

async def main():
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

    logger.info(f"Starting Evok {evok_version} using config directory '{config_path}'.")
    logger.info(f"Setting logging level to '{log_level}'.")

    logger.setLevel(log_level)
    # the root logger is already configured on import, force applies the level to the other libraries too
    logging.basicConfig(level=log_level, force=True)
    if log_level != 'DEBUG':
        # a line for every request only in the debug level
        logging.getLogger('tornado.access').setLevel(logging.WARNING)
        # every attempt to connect a unit, the connection is reported by the scanner of the unit
        logging.getLogger('tmodbus').setLevel(logging.WARNING)
        logging.getLogger('tmodbus.transport.async_smart').setLevel(logging.ERROR)
    log_file = evok_config.logging.get("file", None)
    if log_file is not None:
        # rotating file handler
        filelog_handler = logging.handlers.TimedRotatingFileHandler(filename=log_file, when='D', backupCount=7)
        log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        filelog_handler.setFormatter(log_formatter)
        filelog_handler.setLevel(log_level)
        logger.addHandler(filelog_handler)

    hw_dict = config.HWDict(dir_paths=[f'{config_path}/hw_definitions/'])
    config.load_aliases(alias_file)
    # only the local interface by default, an empty address listens on all interfaces
    address_api = evok_config.apis.get("address", "127.0.0.1") or None
    try:
        auth.set_token(evok_config.apis.get("token"), evok_config.apis.get("read_token"))
        auth.set_allowed_origins(evok_config.apis.get("allowed_origins"))
    except ValueError as E:
        sys.exit(f"evok: {E}")
    if auth.is_enabled():
        logger.info("The API requires the token of the configuration"
                    + (", the read_token allows only reading" if evok_config.apis.get("read_token") else ""))
    else:
        logger.info("The API is not authenticated, set 'token' in 'apis' for an access from the network")

    port_api = evok_config.apis.get("port", 8080)

    api_routes = [
        (r"/rest/all/?", LoadAllHandler),
        (r"/rest/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyRestHandler),
        (r"/bulk/?", JSONBulkHandler),
        (r"/json/all/?", LoadAllHandler),
        (r"/json/([^/]+)/([^/]+)/?([^/]+)?/?", LegacyJsonHandler),
        (r"/version/?", VersionHandler),
        (r"/log/?", LogHandler, dict(log_file=log_file)),
    ]

    # enabled if the section is missing, it was always enabled before the option was added
    if (evok_config.apis.get('rpc') or {}).get('enabled', True):
        api_routes.append((r"/rpc/?", rpc_handler.Handler))
    else:
        logger.info("RPC API is disabled")

    if evok_config.get_api('websocket').get('enabled', False):
        all_filtered = evok_config.get_api('websocket').get("all_filtered", False)
        api_routes.append((r"/ws/?", WsHandler, dict(all_filtered=all_filtered)))

    app = tornado.web.Application(
        handlers=api_routes,
        **WEBSOCKET_SETTINGS
    )

    # ---- prepare http server ----
    # the body is read into the memory before its check, the default of Tornado is 100 MB
    httpServerApi = tornado.httpserver.HTTPServer(app, max_body_size=MAX_BODY_SIZE)
    httpServerApi.listen(port_api, address=address_api)
    logger.info(f"HTTP server API listening on {address_api or 'all interfaces'}:{port_api}")

    webhook_config = evok_config.get_api('webhook')
    if webhook_config.get("enabled", False):
        wh_address = webhook_config.get("address", "http://127.0.0.1:80/index.html")
        wh_types = webhook_config.get("device_mask", ["di", "sensor", "watchdog"])
        wh_complex = webhook_config.get("complex_events", False)
        wh_interval = webhook_config.get("min_interval", 1.0)
        wh = WhHandler(wh_address, wh_types, wh_complex, wh_interval)
        wh.open()

    # ---- prepare hardware according to config ----
    # notify websocket clients and the webhook about changes of devices
    devents.register_status_cb(status_cb)

    # create hw devices
    config.create_devices(evok_config, hw_dict)
    Devices.register_device(RUN, Devices.aliases)

    alias_task = AliasTask(Devices.aliases, alias_file)

    for bustype in [OWBUS]:
        for device in Devices.by_name(bustype):
            device.bus_driver.start_scanning()

    # the devices of a unit are created after its first scan, also without scan_enabled
    for modbus_slave in Devices.by_name(MODBUS_SLAVE):
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
    # the writes ending the pulses do not wait for the scans, a failing unit does not log its errors
    await asyncio.gather(*(modbus_slave.stop_scanning() for modbus_slave in Devices.by_name(MODBUS_SLAVE)))
    # the pulses are timed by evok, do not leave the outputs in the state of a pulse
    await finish_pulses()


def run():
    """Entry point of the evok console script and of python -m evok."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
