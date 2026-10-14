"""The OpenAPI document of the Evok API, generated from the JSON schemas.

``evok.schemas`` is the source of truth for the params (the input of set()) and
the response shapes (the output of full()); this package adds the paths, the
shared components and the document header, and renders the OpenAPI document.

Generate the document with::

    uv run python -m evok.openapi -o Evok_API_OAS.yaml
"""

from . import paths as _paths
from . import shared
from .registry import DEVICES

OPENAPI_VERSION = "3.1.0"


def _without_schema(schema: dict) -> dict:
    """A copy of a JSON schema without its $schema, to embed in the OpenAPI document"""
    return {key: value for key, value in schema.items() if key != "$schema"}


def _device_schemas() -> dict:
    from .. import schemas

    components: dict[str, dict] = dict(shared.SHARED_SCHEMAS)
    for device in DEVICES:
        components[device.component] = _without_schema(schemas.responses[device.response])
        if device.input is not None:
            components[f"{device.component}_params"] = _without_schema(schemas.schemas[device.input][0])
    components["Aliases"] = _without_schema(schemas.responses["run"])
    components["Aliases_params"] = _without_schema(schemas.schemas["run"][0])
    components["Set_alias"] = {
        "title": "Set alias",
        "type": "object",
        "additionalProperties": False,
        "required": ["alias"],
        "properties": {"alias": shared.ALIAS},
    }
    return components


def build_openapi() -> dict:
    """The complete OpenAPI 3.1 document as nested Python dicts"""
    return {
        "openapi": OPENAPI_VERSION,
        "info": shared.INFO,
        "servers": shared.SERVERS,
        "security": shared.SECURITY,
        "tags": shared.TAGS,
        "paths": _paths.build_paths(DEVICES),
        "components": {
            "schemas": _device_schemas(),
            "parameters": shared.PARAMETERS,
            "responses": shared.SHARED_RESPONSES,
            "securitySchemes": shared.SECURITY_SCHEMES,
        },
    }
