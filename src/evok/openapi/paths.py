"""Build the OpenAPI path items from the device registry and the generic endpoints."""

from .registry import DeviceType

FORMAT_REF = {"$ref": "#/components/parameters/format"}
CIRCUIT_REF = {"$ref": "#/components/parameters/circuit"}
DEVICE_TYPE_REF = {"$ref": "#/components/parameters/device_type"}
PARAMETER_REF = {"$ref": "#/components/parameters/parameter"}

_ERRORS = {
    "400": {"$ref": "#/components/responses/BadRequest"},
    "401": {"$ref": "#/components/responses/Unauthorized"},
    "403": {"$ref": "#/components/responses/Forbidden"},
    "404": {"$ref": "#/components/responses/NotFound"},
    "503": {"$ref": "#/components/responses/Unavailable"},
}


def _content(schema):
    return {"application/json": {"schema": schema}, "text/html": {"schema": schema}}


def _device_schema(component: str) -> dict:
    """A single device or an array of the devices of 'all'"""
    return {
        "anyOf": [
            {"$ref": f"#/components/schemas/{component}"},
            {"type": "array", "items": {"$ref": f"#/components/schemas/{component}"}},
        ]
    }


def _write_schema(component: str) -> dict:
    return {"type": "object", "properties": {"success": {"type": "boolean"}, "result": _device_schema(component)}}


def _read_operation(device: DeviceType) -> dict:
    return {
        "tags": [device.tag],
        "summary": device.summary_get,
        "operationId": f"read-{device.segment}-object",
        "responses": {
            "200": {"description": "OK", "content": _content(_device_schema(device.component))},
            **_ERRORS,
        },
    }


def _write_operation(device: DeviceType) -> dict:
    params = {"$ref": f"#/components/schemas/{device.component}_params"}
    return {
        "tags": [device.tag],
        "summary": device.summary_post,
        "operationId": f"post-rest-{device.segment}-circuit",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": params},
                "application/x-www-form-urlencoded": {"schema": params},
            },
        },
        "responses": {
            "200": {"description": "OK", "content": _content(_write_schema(device.component))},
            **_ERRORS,
        },
    }


def device_paths(devices: list[DeviceType]) -> dict:
    paths: dict = {}
    for device in devices:
        item: dict = {"parameters": [FORMAT_REF, CIRCUIT_REF]}
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
                "operationId": "get-all-devices",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "array", "items": {"type": "object"}})},
                    **_ERRORS,
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
                    **_ERRORS,
                },
            },
        },
        "/{format}/{device_type}/{circuit}/{parameter}": {
            "parameters": [FORMAT_REF, DEVICE_TYPE_REF, CIRCUIT_REF, PARAMETER_REF],
            "get": {
                "tags": ["Getter"],
                "summary": "Read one property of a device",
                "operationId": "read-device-parameter",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "object", "additionalProperties": True})},
                    **_ERRORS,
                },
            },
        },
        "/{format}/{device_type}/{circuit}/alias": {
            "parameters": [FORMAT_REF, DEVICE_TYPE_REF, CIRCUIT_REF],
            "post": {
                "tags": ["Aliases"],
                "summary": "Set the alias of a device",
                "operationId": "write-alias-parameter",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Set_alias"}},
                        "application/x-www-form-urlencoded": {"schema": {"$ref": "#/components/schemas/Set_alias"}},
                    },
                },
                "responses": {
                    "200": {"description": "OK", "content": _content({"$ref": "#/components/schemas/Status"})},
                    **_ERRORS,
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
                    "200": {"description": "OK", "content": _content({"$ref": "#/components/schemas/Aliases"})},
                    **_ERRORS,
                },
            },
            "post": {
                "tags": ["Aliases"],
                "summary": "Force save or delete aliases",
                "operationId": "post-force-save-aliases",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Aliases_params"}},
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/Aliases_params"}
                        },
                    },
                },
                "responses": {
                    "200": {"description": "OK", "content": _content({"$ref": "#/components/schemas/Aliases"})},
                    **_ERRORS,
                },
            },
        },
        "/version": {
            "get": {
                "tags": ["General"],
                "summary": "Get the version of Evok",
                "operationId": "get-version",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "string"})},
                    **_ERRORS,
                },
            },
        },
        "/log": {
            "parameters": [
                {"name": "lines", "in": "query", "required": False, "schema": {"type": "integer", "default": 100}}
            ],
            "get": {
                "tags": ["General"],
                "summary": "Get the tail of the log file",
                "operationId": "get-log",
                "responses": {
                    "200": {"description": "OK", "content": _content({"type": "string"})},
                    **_ERRORS,
                },
            },
        },
    }


def build_paths(devices: list[DeviceType]) -> dict:
    paths = generic_paths()
    paths.update(device_paths(devices))
    return paths
