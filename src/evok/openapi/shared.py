"""The parts of the OpenAPI document that are not tied to one device type:

the shared component schemas, the shared error responses, the security schemes,
the path parameters and the document header (info, servers, tags).
"""

from importlib.metadata import PackageNotFoundError, version

from ..devices import devtype_altnames
from ..schemas import COMM_PROPERTIES

try:
    EVOK_VERSION = version("evok")
except PackageNotFoundError:  # pragma: no cover - the package is installed when this runs
    EVOK_VERSION = "unknown"

ALIAS = {
    "type": "string",
    "maxLength": 64,
    "description": "User alias of the device.",
    "examples": ["setpoint_living_room"],
}

# the properties are defined once, with the response schemas in evok.schemas
COMM = {
    "title": "Communication",
    "description": "The communication with the Modbus unit of the device or with a 1-Wire sensor.",
    "type": "object",
    "properties": COMM_PROPERTIES,
}

ERROR = {
    "title": "Error",
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "examples": [False]},
        "errors": {
            "type": "object",
            "description": "Name of the exception and its message.",
            "additionalProperties": {"type": "string"},
        },
    },
}

STATUS = {
    "title": "Status",
    "type": "object",
    "properties": {
        "success": {"type": "boolean", "examples": [True]},
    },
}

SHARED_SCHEMAS: dict[str, dict] = {
    "Alias": ALIAS,
    "Comm": COMM,
    "Error": ERROR,
    "Status": STATUS,
}


def _error(description: str, error: str, message: str) -> dict:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Error"},
                "example": {"success": False, "errors": {error: message}},
            }
        },
    }


# the error responses referenced by the operations
SHARED_RESPONSES: dict[str, dict] = {
    "Unauthorized": {
        "description": "The API requires a token and it is missing or invalid.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    },
    "Forbidden": {
        "description": "The token is valid but reading only is allowed.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    },
    "BadRequest": {
        "description": "An invalid value of a parameter.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    },
    "Unavailable": {
        "description": "The device or the bus is not available.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    },
    "NotFound": {
        "description": "The circuit, the alias or the parameter does not exist.",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
    },
    "SequenceRunning": _error(
        "The output cannot be changed while a pulse or a sequence of its sequencer runs, cancel it there.",
        "SequenceRunning",
        "RO 2_01: a sequence of its sequencer ro_2_01 runs, cancel it there",
    ),
    "ServerError": _error("An internal error, the details are in the log of Evok.", "Server error", "internal"),
}

SECURITY_SCHEMES: dict[str, dict] = {
    "bearerToken": {"type": "http", "scheme": "bearer"},
    "basicToken": {"type": "http", "scheme": "basic"},
}

PARAMETERS: dict[str, dict] = {
    "format": {
        "name": "format",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "enum": ["json", "rest"], "examples": ["json"]},
        "description": "Both return JSON; a POST of *rest* takes the params as a form or a JSON object, "
        "of *json* as a JSON object.",
    },
    "device_type": {
        "name": "device_type",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "examples": ["di"]},
        "description": "The device type, e.g. di, do, ro, ai, temp. Other names of the types: "
        + ", ".join(f"*{name}* ({devtype})" for name, devtype in devtype_altnames.items())
        + ".",
    },
    "circuit": {
        "name": "circuit",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "examples": ["1_01"]},
        "description": "The circuit of the device or *all* for every device of the type.",
    },
    "parameter": {
        "name": "parameter",
        "in": "path",
        "required": True,
        "schema": {"type": "string", "examples": ["value"]},
        "description": "One property of the device, as returned by the full state.",
    },
}

INFO = {
    "title": "Evok",
    "summary": "A web services API for Unipi products",
    "description": "The REST and JSON API of the devices of Evok (the paths /rest/... and /json/...), generated from "
    "the schemas of the sources. The other APIs of Evok, /bulk (several reads and writes in one request), /rpc "
    "(JSON-RPC), /ws (WebSocket) and MQTT, are documented in the pages "
    "[Bulk](https://evok.readthedocs.io/en/stable/apis/bulk/), [RPC](https://evok.readthedocs.io/en/stable/apis/rpc/), "
    "[WebSocket](https://evok.readthedocs.io/en/stable/apis/websocket/) and "
    "[MQTT](https://evok.readthedocs.io/en/stable/apis/mqtt/).",
    "contact": {
        "name": "Evok support",
        "email": "support@unipi.technology",
        "url": "https://github.com/UnipiTechnology/evok",
    },
    "license": {"name": "Apache 2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0.html"},
    "version": EVOK_VERSION,
    "termsOfService": "https://evok.readthedocs.io/",
}

SERVERS = [
    {
        "url": "http://{unipi_device}:{port}",
        "description": "Remote Unipi device",
        "variables": {
            "port": {"default": "8080", "description": "TCP port of the API."},
            "unipi_device": {"default": "192.168.1.2", "description": "IP address or hostname."},
        },
    },
    {
        "url": "http://127.0.0.1:{port}",
        "description": "Localhost",
        "variables": {"port": {"default": "8080", "description": "TCP port of the API."}},
    },
]

# {} is a request without a token, the token is required only when it is set in the configuration
SECURITY = [{}, {"bearerToken": []}, {"basicToken": []}]

TAGS = [
    {"name": "General"},
    {"name": "Getter"},
    {"name": "Setter"},
    {"name": "Analog input"},
    {"name": "Analog output"},
    {"name": "Digital input"},
    {"name": "Digital output"},
    {"name": "Relay output"},
    {"name": "User LED"},
    {"name": "Master watchdog"},
    {"name": "1-Wire bus"},
    {"name": "Modbus register"},
    {"name": "Data point"},
    {"name": "Device info"},
    {"name": "Modbus slave"},
    {"name": "Sequencer"},
    {"name": "Modbus bus"},
    {"name": "Non-volatile memory"},
    {"name": "Aliases"},
]
