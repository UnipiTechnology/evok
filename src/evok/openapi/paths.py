"""Build the OpenAPI path items from the device registry and the generic endpoints."""

from .registry import DeviceType

FORMAT_REF = {"$ref": "#/components/parameters/format"}
CIRCUIT_REF = {"$ref": "#/components/parameters/circuit"}
DEVICE_TYPE_REF = {"$ref": "#/components/parameters/device_type"}
PARAMETER_REF = {"$ref": "#/components/parameters/parameter"}


def _response(name: str) -> dict:
    return {"$ref": f"#/components/responses/{name}"}


# a GET reads the last scanned state, it does not communicate with the unit
_READ_ERRORS = {
    "401": _response("Unauthorized"),
    "404": _response("NotFound"),
    "500": _response("ServerError"),
}

# a POST writes to the unit; 409 only of the outputs driven by a sequencer
_WRITE_ERRORS = {
    "400": _response("BadRequest"),
    "401": _response("Unauthorized"),
    "403": _response("Forbidden"),
    "404": _response("NotFound"),
    "503": _response("Unavailable"),
    "500": _response("ServerError"),
}


def _content(schema):
    return {"application/json": {"schema": schema}}


def _ref(component: str) -> dict:
    return {"$ref": f"#/components/schemas/{component}"}


def _state_schema(device: DeviceType) -> dict:
    """The state of a device of the type, one of more shapes for the 1-Wire sensors"""
    refs = [_ref(component) for component in (device.component, *(c for c, _ in device.alternatives))]
    return refs[0] if len(refs) == 1 else {"oneOf": refs}


def _device_schema(device: DeviceType) -> dict:
    """A single device, or an array of the devices with the circuit 'all'"""
    state = _state_schema(device)
    return {"oneOf": [state, {"type": "array", "items": state}]}


def _result(schema: dict) -> dict:
    """The reply of a POST: the state after the change"""
    return {
        "type": "object",
        "required": ["success", "result"],
        "properties": {"success": {"type": "boolean", "examples": [True]}, "result": schema},
    }


def _request_body(component: str) -> dict:
    """The params of a POST: a form of /rest, a JSON object of /json"""
    return {
        "required": True,
        "description": "The params as a form (`application/x-www-form-urlencoded`) of the format *rest*, "
        "as a JSON object of the format *json*.",
        "content": {
            "application/x-www-form-urlencoded": {"schema": _ref(component)},
            "application/json": {"schema": _ref(component)},
        },
    }


def _read_operation(device: DeviceType) -> dict:
    return {
        "tags": [device.tag],
        "summary": device.summary_get,
        "operationId": f"read-{device.segment}-object",
        "responses": {
            "200": {"description": "OK", "content": _content(_device_schema(device))},
            **_READ_ERRORS,
        },
    }


def _write_operation(device: DeviceType) -> dict:
    errors = dict(_WRITE_ERRORS)
    if device.sequenced:
        errors["409"] = _response("SequenceRunning")
    return {
        "tags": [device.tag],
        "summary": device.summary_post,
        "operationId": f"post-rest-{device.segment}-circuit",
        "requestBody": _request_body(f"{device.component}_params"),
        "responses": {
            "200": {"description": "OK", "content": _content(_result(_state_schema(device)))},
            **dict(sorted(errors.items())),
        },
    }


def device_paths(devices: list[DeviceType]) -> dict:
    paths: dict = {}
    for device in devices:
        item: dict = {"parameters": [FORMAT_REF, CIRCUIT_REF]}
        if device.description:
            item["description"] = device.description
        if device.gettable:
            item["get"] = _read_operation(device)
        if device.settable:
            item["post"] = _write_operation(device)
        paths[f"/{{format}}/{device.segment}/{{circuit}}"] = item
    return paths


def generic_paths() -> dict:
    """The endpoints that are not one device type: all, one parameter, aliases, version, log."""
    return {
        "/{format}/all": {
            "parameters": [FORMAT_REF],
            "get": {
                "tags": ["Getter"],
                "summary": "Get every device",
                "description": "The states of all devices except the sequencers, the Modbus buses "
                "(serial_bus, tcp_bus) and the aliases (run).",
                "operationId": "get-all-devices",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "array", "items": {"type": "object"}})},
                    **_READ_ERRORS,
                },
            },
        },
        "/{format}/{device_type}/all": {
            "parameters": [FORMAT_REF, DEVICE_TYPE_REF],
            "get": {
                "tags": ["Getter"],
                "summary": "Get every device of a device type",
                "operationId": "get-all-devices-of-type",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "array", "items": {"type": "object"}})},
                    **_READ_ERRORS,
                },
            },
        },
        "/{format}/{device_type}/{circuit}/{parameter}": {
            "parameters": [FORMAT_REF, DEVICE_TYPE_REF, CIRCUIT_REF, PARAMETER_REF],
            "get": {
                "tags": ["Getter"],
                "summary": "Read one property of a device",
                "description": "`{\"<parameter>\": <value>}` of a device; with the circuit *all* the list of "
                "`{\"circuit\": ..., \"<parameter>\": ...}`, the devices without the property are skipped.",
                "operationId": "read-device-parameter",
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": _content(
                            {
                                "oneOf": [
                                    {"type": "object", "minProperties": 1, "maxProperties": 1},
                                    {
                                        "type": "array",
                                        "items": {"type": "object", "required": ["circuit"]},
                                    },
                                ]
                            }
                        ),
                    },
                    **_READ_ERRORS,
                },
            },
        },
        "/{format}/{device_type}/{circuit}/alias": {
            "parameters": [FORMAT_REF, DEVICE_TYPE_REF, CIRCUIT_REF],
            "post": {
                "tags": ["Aliases"],
                "summary": "Set the alias of a device",
                "description": "An empty alias removes it. The alias can be set also of a device of an unavailable "
                "Modbus unit.",
                "operationId": "write-alias-parameter",
                "requestBody": _request_body("Set_alias"),
                "responses": {
                    "200": {"description": "OK", "content": _content(_result({"type": "object"}))},
                    **_WRITE_ERRORS,
                },
            },
        },
        "/{format}/run/alias": {
            "parameters": [FORMAT_REF],
            "get": {
                "tags": ["Aliases"],
                "summary": "Read the aliases",
                "operationId": "read-aliases-object",
                "responses": {
                    "200": {"description": "OK", "content": _content(_ref("Aliases"))},
                    **_READ_ERRORS,
                },
            },
            "post": {
                "tags": ["Aliases"],
                "summary": "Force save or delete aliases",
                "operationId": "post-force-save-aliases",
                "requestBody": _request_body("Aliases_params"),
                "responses": {
                    "200": {"description": "OK", "content": _content(_result(_ref("Aliases")))},
                    **_WRITE_ERRORS,
                },
            },
        },
        "/version": {
            "get": {
                "tags": ["General"],
                "summary": "Get the version of Evok",
                "description": "The version as text, e.g. `v3.1.0`; the token is not required.",
                "operationId": "get-version",
                "security": [{}],
                "responses": {
                    "200": {"description": "OK", "content": {"text/html": {"schema": {"type": "string"}}}},
                },
            },
        },
        "/log": {
            "parameters": [
                {
                    "name": "lines",
                    "in": "query",
                    "required": False,
                    "description": "Number of the lines from the end of the log, a value out of the range is clamped.",
                    "schema": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 255},
                }
            ],
            "get": {
                "tags": ["General"],
                "summary": "Get the tail of the log file",
                "description": "Available only with `file` in `logging` of the configuration.",
                "operationId": "get-log",
                "responses": {
                    "200": {"description": "OK", "content": {"text/plain": {"schema": {"type": "string"}}}},
                    "400": {"description": "Invalid number of lines"},
                    "401": _response("Unauthorized"),
                    "404": {"description": "Logging to a file is not configured"},
                },
            },
        },
    }


def build_paths(devices: list[DeviceType]) -> dict:
    paths = generic_paths()
    paths.update(device_paths(devices))
    return paths
