"""JSON schemas of the params of set() of the device types, used by REST, bulk and WebSocket"""

SCHEMA = "https://json-schema.org/draft/2020-12/schema"

# 7: the name of the alias is checked by Aliases.validate(), the length here
MAX_ALIAS_LENGTH = 64
ALIAS = {"type": "string", "maxLength": MAX_ALIAS_LENGTH}

owire_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_sensor",
    "type": "object",
    "additionalProperties": False,
    "properties": {"interval": {"type": ["string", "number"]}, "alias": ALIAS},
}

owire_post_inp_example = {"interval": 15}

led_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Led",
    "type": "object",
    "additionalProperties": False,
    "properties": {"value": {"type": ["boolean", "string", "number"]}, "alias": ALIAS},
}

led_post_inp_example = {"value": "1"}

relay_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Relay",
    "type": "object",
    "additionalProperties": False,
    "properties": {"value": {"type": ["boolean", "string", "number"]}, "alias": ALIAS},
}

relay_post_inp_example = {"value": "1"}

do_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Digital_output",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", "number"]},
        "mode": {"type": "string"},
        "pwm_freq": {"type": ["number", "string"], "minimum": 0},  # 0 is rejected by the device
        "pwm_duty": {"type": ["number", "string"], "minimum": 0, "maximum": 100},
        "alias": ALIAS,
    },
}

do_post_inp_example = {"value": "1"}

ao_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_output",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["string", "number"], "minimum": 0},
        "mode": {"type": "string", "description": "Must be in 'modes', they are given by the hardware definition"},
        "alias": ALIAS,
    },
}

ao_post_inp_example = {"value": 1}

ai_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_input",
    "type": "object",
    "additionalProperties": False,
    "properties": {"mode": {"type": "string", "description": "Must be in 'modes'!"}, "alias": ALIAS},
}

ai_post_inp_example = {"mode": "Voltage"}

di_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Digital_input",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "counter": {"type": ["number", "string"], "minimum": 0, "maximum": 4294967295},
        "counter_mode": {"type": "string"},
        "debounce": {"type": ["number", "string"], "minimum": 0, "maximum": 65535},
        "mode": {"type": "string"},
        "ds_mode": {"type": "string"},
        "alias": ALIAS,
    },
}

di_post_inp_example = {"debounce": 50}

register_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Modbus_register",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["number", "string"],  # the range is checked also for strings by check_params()
            "minimum": 0,
            "maximum": 65535,
        },
        "alias": ALIAS,
    },
}

register_post_inp_example = {"value": "1"}

data_point_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Data_point",
    "type": "object",
    "description": "Writable params of a data point",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["number", "string"],  # the range depends on the datatype, checked by the accessor
            "description": "New value of the data point in its unit, only for a writable data point. "
            "A string is converted to a number.",
            "examples": [21.5, "21.5"],
        },
        "alias": {**ALIAS, "description": "Alias of the data point", "examples": ["setpoint_living_room"]},
    },
}

data_point_post_inp_example = {"value": 21.5}

wd_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Watchdog",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", "number"]},
        "timeout": {"type": ["string", "number"], "minimum": 0},
        "reset": {"type": ["boolean", "string", "number"]},
        "nv_save": {"type": ["boolean", "string", "number"]},
        "alias": ALIAS,
    },
}

wd_post_inp_example = {"value": "1"}

owbus_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_bus",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "do_scan": {
            "type": ["boolean", "number", "string"]  # a form of REST sends strings, converted by to_bool()
        },
        "do_reset": {"type": ["boolean", "number", "string"]},
        "interval": {"type": ["number", "string"]},
        "scan_interval": {"type": ["number", "string"]},
    },
}

owbus_post_inp_example = {"do_reset": True, "do_scan": True}

modbus_slave_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Modbus_slave",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "scan_enabled": {
            "type": ["boolean", "number", "string"]  # a form of REST sends strings, converted by to_bool()
        },
        "alias": ALIAS,
    },
}

modbus_slave_post_inp_example = {"scan_enabled": False}

owpower_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_power",
    "type": "object",
    "additionalProperties": False,
    "properties": {"value": {"type": ["number", "string", "boolean"]}, "alias": ALIAS},
}

owpower_post_inp_example = {"value": True}

run_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Aliases",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "save": {"type": ["string", "number", "boolean"]},
        "delete": {
            "type": "string",
            "description": "Alias to delete, also an alias of a device which is not registered (e.g. offline)",
        },
    },
}

run_post_inp_example = {"save": True}

nv_save_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "NV_save",
    "type": "object",
    "additionalProperties": False,
    "properties": {"value": {"type": ["number", "string", "boolean"]}, "alias": ALIAS},
}

nv_save_post_inp_example = {"value": 1}

_bulk_group = {"type": ["string", "number"]}
_bulk_circuits = {"type": "array", "items": {"type": "string"}}

bulk_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Bulk",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "group_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["device_types"],
                "properties": {
                    "device_types": {"type": "array", "items": {"type": "string"}},
                    "group": _bulk_group,
                    "device_circuits": _bulk_circuits,
                },
            },
        },
        "group_assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["device_type", "assigned_values"],
                "properties": {
                    "device_type": {"type": "string"},
                    "assigned_values": {"type": "object"},  # checked by the schema of the device_type
                    "group": _bulk_group,
                    "device_circuits": _bulk_circuits,
                },
            },
        },
        "individual_assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["device_type", "device_circuit", "assigned_values"],
                "properties": {
                    "device_type": {"type": "string"},
                    "device_circuit": {"type": ["string", "number"]},
                    "assigned_values": {"type": "object"},  # checked by the schema of the device_type
                },
            },
        },
    },
}

bulk_post_inp_example = {
    "individual_assignments": [{"device_type": "do", "device_circuit": "1_01", "assigned_values": {"value": 1}}]
}


sequencer_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Sequencer",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", "number"]},
        "pulse_duration": {"type": ["number", "string"], "minimum": 0},  # 0 is rejected by the sequencer
        # {"delay": seconds, <the params of the output>}, the params are checked by the schema of the output
        "steps": {"type": "array", "items": {"type": "object"}},
        "final": {"type": "object"},
        "cancel": {"type": ["boolean", "string", "number"]},
        "alias": ALIAS,
    },
}

sequencer_post_inp_example = {"value": 1, "pulse_duration": 2}

schemas: dict[str, tuple[dict, dict]] = {
    "input": (di_post_inp_schema, di_post_inp_example),
    "output": (do_post_inp_schema, do_post_inp_example),
    "ro": (relay_post_inp_schema, relay_post_inp_example),
    "register": (register_post_inp_schema, register_post_inp_example),
    "data_point": (data_point_post_inp_schema, data_point_post_inp_example),
    "ai": (ai_post_inp_schema, ai_post_inp_example),
    "ao": (ao_post_inp_schema, ao_post_inp_example),
    "led": (led_post_inp_schema, led_post_inp_example),
    "watchdog": (wd_post_inp_schema, wd_post_inp_example),
    "1wdevice": (owire_post_inp_schema, owire_post_inp_example),
    "owbus": (owbus_post_inp_schema, owbus_post_inp_example),
    "modbus_slave": (modbus_slave_post_inp_schema, modbus_slave_post_inp_example),
    "owpower": (owpower_post_inp_schema, owpower_post_inp_example),
    "run": (run_post_inp_schema, run_post_inp_example),
    "nv_save": (nv_save_post_inp_schema, nv_save_post_inp_example),
    "sequencer": (sequencer_post_inp_schema, sequencer_post_inp_example),
}
schemas["di"] = schemas["input"]
schemas["digitalinput"] = schemas["input"]
schemas["do"] = schemas["output"]
schemas["digitaloutput"] = schemas["output"]
schemas["relay"] = schemas["ro"]
schemas["analoginput"] = schemas["ai"]
schemas["analogoutput"] = schemas["ao"]
schemas["wd"] = schemas["watchdog"]
schemas["temp"] = schemas["1wdevice"]
schemas["sensor"] = schemas["1wdevice"]


# # response schemas: the state returned by full() of each device type.
# The shared fragments (Comm) are inlined so a response schema is self-contained,
# both for the generated OpenAPI document and for the black-box integration tests.

# the properties shared by every device, referenced also by the OpenAPI Comm component
COMM_PROPERTIES = {
    "comm": {
        "type": "string",
        "enum": ["ok", "timeout", "error"],
        "readOnly": True,
        "description": "*ok* - the last scan of the unit (the read of the sensor) succeeded; *timeout* - "
        "the unit does not respond; *error* - another error, e.g. a CRC error. The value is "
        "the last known one, valid with *ok*.",
    },
    "last_comm": {
        "type": ["number", "null"],
        "examples": [0.04],
        "readOnly": True,
        "description": "Seconds since the last successful communication, *null* if there was none yet.",
    },
}

_ALIAS_RESP = {**ALIAS, "description": "User alias of the device, present only when one is set.", "readOnly": True}


def _response(title, properties, required=(), description=None):
    """A full() response schema; dev/circuit/comm/last_comm are common to every device"""
    schema = {
        "$schema": SCHEMA,
        "title": title,
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "dev": {"type": "string", "description": "Device type.", "readOnly": True},
            "circuit": {
                "type": "string",
                "description": "The circuit of the device, see "
                "[circuit](https://evok.readthedocs.io/en/stable/circuit/).",
                "readOnly": True,
            },
            **COMM_PROPERTIES,
            **properties,
        },
        "required": ["dev", "circuit", *required],
    }
    if description is not None:
        schema["description"] = description
    return schema


di_resp_schema = _response(
    "Digital input",
    {
        "value": {
            "type": ["integer", "null"],
            "description": "The current level, 0 or 1, null before the first scan.",
            "readOnly": True,
        },
        "debounce": {"type": ["integer", "null"], "description": "Debounce of the input in ms."},
        "counter_modes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Supported counter modes.",
            "readOnly": True,
        },
        "counter_mode": {"type": "string", "description": "Enabled or Disabled."},
        "counter": {
            "type": ["integer", "null"],
            "description": "Counter value, 0 when the counter is disabled.",
            "readOnly": True,
        },
        "mode": {"type": "string", "description": "Simple or DirectSwitch."},
        "modes": {"type": "array", "items": {"type": "string"}, "description": "Supported modes.", "readOnly": True},
        "ds_mode": {"type": "string", "description": "DirectSwitch mode, present only in DirectSwitch."},
        "ds_modes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Supported DirectSwitch modes, present only in DirectSwitch.",
            "readOnly": True,
        },
        "alias": _ALIAS_RESP,
    },
    required=("value", "mode", "modes"),
)

do_resp_schema = _response(
    "Digital output",
    {
        "value": {"type": ["integer", "null"], "description": "The current state, 0 or 1, null before the first scan."},
        "mode": {"type": ["string", "null"], "description": "Simple or PWM, null before the first scan."},
        "modes": {"type": "array", "items": {"type": "string"}, "description": "Supported modes.", "readOnly": True},
        "pwm_freq": {
            "type": ["number", "null"],
            "description": "PWM frequency in Hz, null without PWM.",
            "readOnly": True,
        },
        "pwm_duty": {
            "type": ["number", "null"],
            "description": "PWM duty cycle in %, null without PWM.",
            "readOnly": True,
        },
        "alias": _ALIAS_RESP,
    },
    required=("value", "mode", "modes"),
)

ro_resp_schema = _response(
    "Relay output",
    {
        "value": {"type": ["integer", "null"], "description": "The current state, 0 or 1, null before the first scan."},
        "alias": _ALIAS_RESP,
    },
    required=("value",),
)

led_resp_schema = _response(
    "User LED",
    {
        "value": {"type": ["integer", "null"], "description": "The current state, 0 or 1, null before the first scan."},
        "alias": _ALIAS_RESP,
    },
    required=("value",),
)

ai_resp_schema = _response(
    "Analog input",
    {
        "value": {
            "type": ["number", "string", "null"],
            "description": "The measured value in the unit of the mode; 'NaN', 'Infinity' or '-Infinity' for a value "
            "which is not a number, null before the first scan.",
            "readOnly": True,
        },
        "unit": {
            "type": ["string", "null"],
            "description": "Unit of the value, null without a mode.",
            "readOnly": True,
        },
        "mode": {"type": ["string", "null"], "description": "The current mode."},
        "modes": {
            "type": "object",
            "description": "Supported modes with their unit and range, from the HW definition.",
            "additionalProperties": {
                "type": "object",
                "properties": {"unit": {"type": "string"}, "range": {"type": "array", "items": {"type": "number"}}},
            },
            "readOnly": True,
        },
        "range": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "description": "Allowed range of the value in the current mode, null without a mode.",
            "readOnly": True,
        },
        "alias": _ALIAS_RESP,
    },
    required=("value", "mode", "modes"),
)

ao_resp_schema = _response(
    "Analog output",
    {
        "value": {
            "type": ["number", "string", "null"],
            "description": "The output value in the unit of the mode, null before the first scan.",
        },
        "unit": {
            "type": ["string", "null"],
            "description": "Unit of the value, null without a mode.",
            "readOnly": True,
        },
        "mode": {"type": ["string", "null"], "description": "The current mode."},
        "modes": {
            "type": "object",
            "description": "Supported modes with their unit and range, from the HW definition.",
            "additionalProperties": {
                "type": "object",
                "properties": {"unit": {"type": "string"}, "range": {"type": "array", "items": {"type": "number"}}},
            },
            "readOnly": True,
        },
        "range": {
            "type": ["array", "null"],
            "items": {"type": "number"},
            "description": "Allowed range of the value in the current mode, null without a mode.",
            "readOnly": True,
        },
        "alias": _ALIAS_RESP,
    },
    required=("value", "mode", "modes"),
)

wd_resp_schema = _response(
    "Master watchdog",
    {
        "value": {"type": ["integer", "null"], "description": "1 when the watchdog is enabled."},
        "timeout": {"type": ["integer", "null"], "description": "Watchdog timeout in ms."},
        "was_wd_reset": {
            "type": ["integer", "null"],
            "description": "Binary flag indicating a restart caused by the watchdog.",
            "readOnly": True,
        },
        "alias": _ALIAS_RESP,
    },
    required=("value", "timeout", "was_wd_reset"),
)

register_resp_schema = _response(
    "Modbus register",
    {
        "value": {"type": ["integer", "null"], "description": "The register value, null before the first scan."},
        "alias": _ALIAS_RESP,
    },
    required=("value",),
)

data_point_resp_schema = _response(
    "Data point",
    {
        "value": {
            "type": ["number", "string", "null"],
            "description": "The value in its unit; 'NaN', 'Infinity' or '-Infinity' for a value which is not a number.",
        },
        "writable": {"type": "boolean", "description": "The register is writable.", "readOnly": True},
        "name": {"type": "string", "description": "Name of the data point, when configured.", "readOnly": True},
        "unit": {"type": "string", "description": "Unit of the value, when configured.", "readOnly": True},
        "alias": _ALIAS_RESP,
        "valid": {
            "type": ["boolean", "null"],
            "description": "The value is valid, only with valid_mask_reg (a 1-Wire thermometer of xG18).",
            "readOnly": True,
        },
    },
    required=("value",),
)

owpower_resp_schema = _response(
    "1-Wire power supply",
    {
        "value": {"type": "integer", "description": "1 when the power is on."},
        "alias": _ALIAS_RESP,
    },
    required=("value",),
)

nv_save_resp_schema = _response(
    "Non-volatile memory",
    {
        "value": {"type": "integer", "description": "1 while the settings are saved."},
        "alias": _ALIAS_RESP,
    },
    required=("value",),
)

owbus_resp_schema = _response(
    "1-Wire bus",
    {
        "bus": {"type": "string", "description": "Access method to the bus.", "readOnly": True},
        "master": {
            "type": ["string", "null"],
            "description": "The 1-Wire master of the kernel used by the bus.",
            "readOnly": True,
        },
        "scan_interval": {"type": "number", "description": "Interval of a bus scan in s."},
        "interval": {"type": "number", "description": "Interval of the sensor reads in s."},
        "do_scan": {"type": "boolean", "description": "Scan the bus (write-only)."},
        "do_reset": {"type": "boolean", "description": "Reset the 1-Wire master by owpower (write-only)."},
    },
    required=("bus", "scan_interval", "interval"),
)

temp_resp_schema = _response(
    "Temperature sensor",
    {
        "address": {"type": "string", "description": "1-Wire address in the form of owserver.", "readOnly": True},
        "value": {"type": ["number", "null"], "description": "Temperature in \u00b0C."},
        "lost": {"type": "boolean", "description": "The sensor is not found on the bus.", "readOnly": True},
        "time": {"type": "number", "description": "Loop time of the last read, deprecated.", "readOnly": True},
        "interval": {"type": "number", "description": "Interval of the reads in s."},
        "type": {"type": "string", "description": "Type of the 1-Wire sensor.", "readOnly": True},
        "alias": _ALIAS_RESP,
    },
    required=("address", "value", "lost", "interval", "type"),
)

onewire_resp_schema = _response(
    "1-Wire device",
    {
        "address": {"type": "string", "description": "1-Wire address in the form of owserver.", "readOnly": True},
        "value": {"description": "The values of the device: the PIO levels of a DS2408, the readings of a DS2438."},
        "humidity": {
            "type": ["number", "null"],
            "description": "Relative humidity of a HIH4000 (DS2438), in %.",
            "readOnly": True,
        },
        "vdd": {"type": ["number", "null"], "description": "Supply voltage of a DS2438, in V.", "readOnly": True},
        "vad": {"type": ["number", "null"], "description": "VAD input of a DS2438, in V.", "readOnly": True},
        "temp": {"type": ["number", "null"], "description": "Temperature of a DS2438, in \u00b0C.", "readOnly": True},
        "vis": {
            "type": ["number", "null"],
            "description": "Current of a DS2438, in V over the sense resistor.",
            "readOnly": True,
        },
        "lost": {"type": "boolean", "description": "The sensor is not found on the bus.", "readOnly": True},
        "time": {"type": "number", "description": "Loop time of the last read, deprecated.", "readOnly": True},
        "interval": {"type": "number", "description": "Interval of the reads in s."},
        "type": {"type": "string", "description": "Type of the 1-Wire sensor.", "readOnly": True},
        "alias": _ALIAS_RESP,
    },
    required=("lost", "interval", "type"),
)

modbus_slave_resp_schema = _response(
    "Modbus slave",
    {
        "slave_id": {"type": "integer", "description": "Modbus address (slave id) of the unit.", "readOnly": True},
        "modbus_type": {"type": "string", "description": "Type of the bus.", "readOnly": True},
        "modbus_spec": {"type": "string", "description": "Specification of the bus.", "readOnly": True},
        "scan_interval": {
            "type": "number",
            "description": "Interval of the scans in s, 1 / scan_frequency.",
            "readOnly": True,
        },
        "scan_enabled": {"type": "boolean", "description": "The scanning of the unit is enabled."},
        "scan_error": {"type": ["string", "null"], "description": "Reason of the last failed scan.", "readOnly": True},
    },
    required=("slave_id", "scan_interval", "scan_enabled"),
)

device_info_resp_schema = _response(
    "Device info",
    {
        "family": {"type": "string", "description": "Family of the controller.", "readOnly": True},
        "model": {"type": "string", "description": "Model of the controller.", "readOnly": True},
        "sn": {"type": ["integer", "null"], "description": "Serial number.", "readOnly": True},
        "board_count": {"type": "integer", "description": "Number of boards.", "readOnly": True},
    },
    required=("family", "model", "board_count"),
)

_BUS_DEVICES = {
    "type": "array",
    "items": {"type": "string"},
    "description": "The circuits of the Modbus units of the bus.",
    "readOnly": True,
}
_BUS_COMMON = {
    "timeout": {"type": "number", "description": "Timeout of a response in s.", "readOnly": True},
    "retries": {"type": "integer", "description": "Retries of a failed request.", "readOnly": True},
    "probe_timeout": {
        "type": "number",
        "description": "Timeout of the probe of a unit which does not respond, in s.",
        "readOnly": True,
    },
}
serial_bus_resp_schema = _response(
    "Modbus RTU bus",
    {
        "port": {"type": "string", "description": "The serial port.", "readOnly": True},
        "baudrate": {"type": "integer", "readOnly": True},
        "parity": {"type": "string", "enum": ["N", "E", "O"], "readOnly": True},
        "stopbits": {"type": "integer", "readOnly": True},
        **_BUS_COMMON,
        "devices": _BUS_DEVICES,
    },
    required=("port", "devices"),
)
tcp_bus_resp_schema = _response(
    "Modbus TCP bus",
    {
        "hostname": {"type": "string", "description": "The Modbus TCP server.", "readOnly": True},
        "port": {"type": "integer", "readOnly": True},
        "connect_timeout": {"type": "number", "description": "Timeout of the connection in s.", "readOnly": True},
        **_BUS_COMMON,
        "devices": _BUS_DEVICES,
    },
    required=("hostname", "port", "devices"),
)

sequencer_resp_schema = _response(
    "Sequencer",
    {
        "output": {
            "type": "object",
            "description": "The device the sequencer drives.",
            "properties": {"dev": {"type": "string"}, "circuit": {"type": "string"}},
            "readOnly": True,
        },
        "running": {"type": "boolean", "description": "A pulse or a sequence is running.", "readOnly": True},
        "name": {"type": ["string", "null"], "description": "Name of the running sequence.", "readOnly": True},
        "step": {"type": ["integer", "null"], "description": "Index of the running step.", "readOnly": True},
        "steps": {"type": ["integer", "null"], "description": "Number of the steps of the sequence.", "readOnly": True},
        "alias": _ALIAS_RESP,
    },
    required=("output", "running"),
)

run_resp_schema = _response(
    "Aliases",
    {
        "save": {"type": "boolean", "description": "Force saving of the aliases to the file."},
        "aliases": {
            "type": "object",
            "description": "The aliases by name.",
            "additionalProperties": {"type": "object"},
        },
    },
    required=("aliases",),
)

responses: dict[str, dict] = {
    "di": di_resp_schema,
    "do": do_resp_schema,
    "ro": ro_resp_schema,
    "led": led_resp_schema,
    "ai": ai_resp_schema,
    "ao": ao_resp_schema,
    "wd": wd_resp_schema,
    "watchdog": wd_resp_schema,
    "register": register_resp_schema,
    "data_point": data_point_resp_schema,
    "owpower": owpower_resp_schema,
    "nv_save": nv_save_resp_schema,
    "owbus": owbus_resp_schema,
    "temp": temp_resp_schema,
    "1wdevice": onewire_resp_schema,
    "sensor": temp_resp_schema,
    "modbus_slave": modbus_slave_resp_schema,
    "device_info": device_info_resp_schema,
    "serial_bus": serial_bus_resp_schema,
    "tcp_bus": tcp_bus_resp_schema,
    "sequencer": sequencer_resp_schema,
    "run": run_resp_schema,
}


# # the documentation of the schemas in the OpenAPI document: the descriptions and the examples,
# they do not change the validation of the params

_DOCS = "https://evok.readthedocs.io/en/stable"


def _document(schema: dict, description: str | None = None, examples: list | None = None, **properties):
    """Add the description, the examples of the whole object and the notes of its properties;
    a property gets a copy, the fragments as ALIAS are shared by more schemas
    """
    if description is not None:
        schema["description"] = description
    if examples is not None:
        schema["examples"] = examples
    for name, notes in properties.items():
        schema["properties"][name] = {**schema["properties"][name], **notes}


def _alias(example: str) -> dict:
    return {"description": "Alias of the device, an empty string deletes it.", "examples": [example]}


_OUTPUT_VALUE = (
    "The value of the output: a boolean, also `0`, `1` or a string `'true'`, `'on'`, `'1'`, `'false'`, "
    "`'off'`, `'0'`. A pulse is set by the [sequencer](" + _DOCS + "/apis/sequencer/) of the output."
)

# the params of a POST
_document(
    di_post_inp_schema,
    "The params of a digital input.",
    [{"debounce": 100}, {"counter": 0}],
    debounce={"description": "Debounce time in milliseconds/10 (10 == 1 ms).", "examples": [100]},
    counter={"description": "A new value of the counter.", "examples": [0]},
    counter_mode={
        "description": "__Deprecated__. Disabled only reports the counter as 0, the input counts "
        "anyway. The mode is kept by Evok, it is not saved, it is Enabled again after a restart of "
        "Evok.",
        "examples": ["Enabled", "Disabled"],
        "deprecated": True,
    },
    mode={
        "description": "For DirectSwitch read the manual of the unit, it is not available on all inputs.",
        "examples": ["Simple", "DirectSwitch"],
    },
    ds_mode={
        "description": "Behaviour of the DirectSwitch mode, it can be set only in the DirectSwitch mode, "
        "also together with the mode DirectSwitch.",
        "examples": ["Simple", "Inverted", "Toggle"],
    },
    alias=_alias("my_input"),
)
_document(
    do_post_inp_schema,
    "The params of a digital output.",
    [{"value": 1}, {"mode": "PWM", "pwm_duty": 25}],
    value={"description": _OUTPUT_VALUE + " It is mutually exclusive with *pwm_duty*.", "examples": [1, True]},
    mode={"examples": ["Simple", "PWM"]},
    pwm_freq={
        "description": "Frequency in Hz shared by the PWM outputs of the group, up to 50000 Hz on the "
        "boards with a HW timer, up to 1000 Hz with the PWM of the firmware. The nearest available "
        "frequency is set, the result has it. Setting it on an output without PWM is an error.",
        "examples": [50, 1000, 50000],
    },
    pwm_duty={
        "description": "Duty cycle in percent, a float; the state has it rounded to 0.1 (to an integer "
        "with the PWM of the firmware). It is mutually exclusive with *value*, except 0 with value 0 "
        "and 100 with value 1.",
        "examples": [0, 25, 50.5, 100],
    },
    alias=_alias("my_output"),
)
_document(
    relay_post_inp_schema,
    "The params of a relay output.",
    [{"value": 1}],
    value={"description": _OUTPUT_VALUE, "examples": [0, 1, True]},
    alias=_alias("my_relay"),
)
_document(
    led_post_inp_schema,
    "The params of a user LED.",
    [{"value": 1}, {"value": 0}],
    value={"description": _OUTPUT_VALUE, "examples": [1]},
    alias=_alias("my_led"),
)
_document(
    ai_post_inp_schema,
    "The params of an analog input.",
    [{"mode": "Voltage"}],
    mode={
        "description": "One of the keys of *modes* of the state, given by the [HW definition]("
        + _DOCS
        + "/configs/hw_definitions/), e.g. Voltage, Current or Resistance3W.",
        "examples": ["Voltage"],
    },
    alias=_alias("my_analog_input"),
)
_document(
    ao_post_inp_schema,
    "The params of an analog output.",
    [{"value": 5.5}, {"mode": "Current", "value": 10}],
    value={
        "description": "The value in the unit of the mode, a string is converted to a number.",
        "examples": [0.01, 2.1, 5.5],
    },
    mode={
        "description": "One of the keys of *modes* of the state, Voltage, Current or Resistance on the Neuron "
        "boards, given by the HW definition on the other units.",
        "examples": ["Voltage"],
    },
    alias=_alias("my_analog_output"),
)
_document(
    wd_post_inp_schema,
    "The params of the master watchdog of a Modbus unit.",
    [{"value": 1, "timeout": 5000}],
    value={
        "description": "Enable (1) or disable (0) the master watchdog. The write clears *was_wd_reset*.",
        "examples": [1],
    },
    timeout={
        "description": "The timeout in ms, a string is converted to an integer, a value over 65535 is "
        "clamped to 65535.",
        "examples": [3000],
    },
    reset={
        "description": "A true value (also `1` or `'true'` in a form) restarts the Modbus unit at once, only "
        "on a unit with the reset coil in its HW definition, it is ignored on the others.",
        "examples": [True],
    },
    nv_save={
        "description": "__Deprecated__ and not supported, setting it is an error. Use the device "
        "*nv_save* of the unit.",
        "deprecated": True,
    },
    alias=_alias("my_watchdog"),
)
_document(
    owire_post_inp_schema,
    "The params of a 1-Wire sensor.",
    [{"interval": 15}],
    interval={
        "description": "Period of the reads in seconds, a positive number truncated to an integer, also "
        "a string. The default is 15 s of a sensor of the configuration, the interval of the bus of a "
        "found sensor.",
        "examples": [10, 30],
    },
    alias=_alias("my_sensor"),
)
_document(
    owbus_post_inp_schema,
    "The params of a 1-Wire bus.",
    [{"do_scan": True}, {"interval": 30}],
    do_scan={"description": "Start the search for new devices, also `1` or `'true'` in a form."},
    do_reset={"description": "Reset the 1-Wire master by owpower, also `1` or `'true'` in a form."},
    interval={
        "description": "Period of the reads of the sensors in seconds, it is set to all sensors of the bus; "
        "a positive number truncated to an integer, also a string.",
        "examples": [10, 30],
    },
    scan_interval={
        "description": "Period of the search for new devices in seconds, truncated to an integer, "
        "also a string; 0 searches only after the start and on *do_scan*.",
        "examples": [60, 300],
    },
)
_document(
    modbus_slave_post_inp_schema,
    "The params of a Modbus unit.",
    [{"scan_enabled": False}],
    scan_enabled={
        "description": "Enable or disable the periodic scan, also `1` or `'true'` in a form. `true` "
        "also starts again a scan stopped by an error. The first scan, which creates the devices of "
        "the unit, runs also with `false`.",
        "examples": [False],
    },
    alias=_alias("unit_1"),
)
_document(
    owpower_post_inp_schema,
    "The params of the power of a 1-Wire bus.",
    [{"value": 1}],
    value={
        "description": "1 (also true or '1') disables the power of the 1-Wire bus, 0 powers the bus. The "
        "state has 0 or 1.",
        "examples": [0, 1, True],
    },
    alias=_alias("my_owpower"),
)
_document(
    nv_save_post_inp_schema,
    "Save the settings of a Modbus unit to its non-volatile memory.",
    [{"value": 1}],
    value={
        "description": "1 (also true or '1') saves the settings (PWM, debounce, DO, AO, DirectSwitch ...) "
        "which the unit loads after its restart, 0 does nothing. The state has 1 for 2 s after the write, "
        "a new write is refused (400) until then.",
        "examples": [1, True],
    },
    alias=_alias("my_nv_save"),
)
_document(
    register_post_inp_schema,
    "The params of a Modbus register.",
    [{"value": 200}],
    value={
        "description": "A new raw value of the register, a string is converted to a number.",
        "examples": [0, 200, "200"],
    },
    alias=_alias("my_register"),
)
_document(data_point_post_inp_schema, "The params of a data point.", [{"value": 21.5}])
_document(
    run_post_inp_schema,
    "Save or delete the aliases.",
    [{"save": True}, {"delete": "my_relay"}],
    save={
        "description": "Save the aliases to the file of the aliases at once, also `1` or `'true'` in a "
        "form; they are saved also 5 minutes after a change."
    },
    delete={"examples": ["my_relay"]},
)
_document(
    sequencer_post_inp_schema,
    "One of: *value* with *pulse_duration* sets the value of the output for a "
    "pulse; *steps* (and *final*) run a sequence of changes of the output; *cancel* stops the running sequence "
    "without its final state. See [Sequencer](" + _DOCS + "/apis/sequencer/).",
    [
        {"value": 1, "pulse_duration": 2},
        {"steps": [{"value": 1}, {"delay": 0.5, "value": 0}], "final": {"value": 0}},
        {"cancel": True},
    ],
    value={"description": "The value of the output for the pulse, it requires *pulse_duration*."},
    pulse_duration={
        "description": "Duration of the pulse in seconds, the output is set to the opposite of "
        "*value* after it. The pulse is timed by Evok, it is ended on shutdown, but not after a "
        "crash of Evok.",
        "examples": [0.5, 5],
    },
    steps={
        "description": "The steps of the sequence, 1 to 100: the params of the output with an optional "
        "*delay* in seconds before the step."
    },
    final={"description": "The params of the output written when the sequence is ended on shutdown."},
    cancel={"description": "Stop the running sequence without its final state."},
    alias=_alias("pump_pulse"),
)

# the states of full()
_COMM = {"comm": "ok", "last_comm": 0.041}
_document(
    di_resp_schema,
    "The state of a digital input.",
    [
        {
            "dev": "di",
            "circuit": "1_01",
            "value": 0,
            "debounce": 50,
            "counter_modes": ["Enabled", "Disabled"],
            "counter_mode": "Enabled",
            "counter": 0,
            "mode": "Simple",
            "modes": ["Simple", "DirectSwitch"],
            **_COMM,
        },
        {
            "dev": "di",
            "circuit": "1_02",
            "value": 1,
            "debounce": 200,
            "counter_modes": ["Enabled", "Disabled"],
            "counter_mode": "Enabled",
            "counter": 121,
            "mode": "Simple",
            "modes": ["Simple", "DirectSwitch"],
            **_COMM,
            "alias": "switch_living_room",
        },
    ],
    counter_modes={"deprecated": True},
    counter_mode={"deprecated": True},
)
_document(
    do_resp_schema,
    "The state of a digital output.",
    [
        {
            "dev": "do",
            "circuit": "1_01",
            "value": 0,
            "mode": "Simple",
            "modes": ["Simple", "PWM"],
            "pwm_freq": 4800.0,
            "pwm_duty": 0,
            **_COMM,
        },
        {
            "dev": "do",
            "circuit": "1_02",
            "value": 0,
            "mode": "PWM",
            "modes": ["Simple", "PWM"],
            "pwm_freq": 4800.0,
            "pwm_duty": 10,
            **_COMM,
        },
    ],
)
_document(ro_resp_schema, "The state of a relay output.", [{"dev": "ro", "circuit": "2_01", "value": 1, **_COMM}])
_document(led_resp_schema, "The state of a user LED.", [{"dev": "led", "circuit": "1_01", "value": 0, **_COMM}])
_AI_MODES = {"Voltage": {"unit": "V", "range": [0, 10]}, "Current": {"unit": "mA", "range": [0, 20]}}
_document(
    ai_resp_schema,
    "The state of an analog input; its modes are given by the [HW definition](" + _DOCS + "/configs/hw_definitions/).",
    [
        {
            "dev": "ai",
            "circuit": "2_01",
            "value": 2.2,
            "unit": "V",
            "mode": "Voltage",
            "modes": _AI_MODES,
            "range": [0, 10],
            **_COMM,
        },
        {
            "dev": "ai",
            "circuit": "2_02",
            "value": "NaN",
            "unit": "mA",
            "mode": "Current",
            "modes": _AI_MODES,
            "range": [0, 20],
            **_COMM,
        },
    ],
)
_document(
    ao_resp_schema,
    "The state of an analog output.",
    [
        {
            "dev": "ao",
            "circuit": "2_01",
            "value": 1.4,
            "unit": "V",
            "mode": "Voltage",
            "modes": {"Voltage": {"unit": "V", "range": [0, 10]}},
            "range": [0, 10],
            **_COMM,
        },
    ],
)
_document(
    wd_resp_schema,
    "The state of the master watchdog of a Modbus unit, see the [master watchdog]("
    "https://kb.unipi.technology/en:hw:007-patron:description-of-io:02-description-of-do#mwd).",
    [
        {"dev": "wd", "circuit": "1", "value": 0, "timeout": 5000, "was_wd_reset": 0, **_COMM},
    ],
)
_document(
    register_resp_schema,
    "The raw value of a Modbus register; the feature REGISTER is deprecated, a data "
    "point of uint16 is the same register.",
    [{"dev": "register", "circuit": "1_1000", "value": 16256, **_COMM}],
)
_document(
    data_point_resp_schema,
    "The value of a data point of a Modbus unit, as given by its [HW definition]("
    + _DOCS
    + "/configs/hw_definitions/), e.g. CO2 of an IAQ sensor.",
    [
        {
            "dev": "data_point",
            "circuit": "IAQ_0",
            "value": 458.16,
            "writable": False,
            "name": "CO2",
            "unit": "ppm",
            **_COMM,
        },
        {
            "dev": "data_point",
            "circuit": "xG18_2",
            "value": 21.5,
            "writable": False,
            "name": "temperature",
            "unit": "C",
            **_COMM,
            "valid": True,
        },
    ],
    name={"examples": ["CO2"]},
    unit={"examples": ["ppm"]},
)
_document(owpower_resp_schema, "The power of a 1-Wire bus.", [{"dev": "owpower", "circuit": "1", "value": 0, **_COMM}])
_document(
    nv_save_resp_schema,
    "The saving to the non-volatile memory of a Modbus unit, value 1 for 2 s after a save.",
    [{"dev": "nv_save", "circuit": "1", "value": 0, **_COMM}],
)
_document(
    owbus_resp_schema,
    "A 1-Wire bus read by the kernel.",
    [
        {
            "dev": "owbus",
            "circuit": "OWFS",
            "bus": "OWFS",
            "master": "w1_bus_master1",
            "scan_interval": 300,
            "interval": 60,
            "do_scan": False,
            "do_reset": False,
        },
    ],
)
_document(
    temp_resp_schema,
    "A 1-Wire thermometer.",
    [
        {
            "dev": "temp",
            "circuit": "2895DCD509000035",
            "address": "28.95DCD5090000.35",
            "value": 23.0,
            "lost": False,
            "time": 4306.778,
            "interval": 15,
            "type": "DS18B20",
            **_COMM,
        },
    ],
    time={"deprecated": True},
)
_document(
    onewire_resp_schema,
    "Another 1-Wire device: a DS2438 (e.g. a humidity sensor with HIH4000) or the "
    "levels of the PIOs of a DS2408, DS2406 or DS2413.",
    [
        {
            "dev": "1wdevice",
            "circuit": "26F0A2CB01000077",
            "humidity": 45.12,
            "vdd": 5.02,
            "vad": 2.13,
            "temp": 22.5,
            "vis": 0.0002441,
            "lost": False,
            "time": 4306.778,
            "interval": 15,
            "type": "DS2438",
            **_COMM,
        },
        {
            "dev": "1wdevice",
            "circuit": "29.1D9F0F000000",
            "address": "29.1D9F0F000000",
            "value": [1, 1, 0, 1, 1, 1, 1, 1],
            "lost": False,
            "time": 4306.778,
            "interval": 15,
            "type": "DS2408",
            **_COMM,
        },
    ],
    time={"deprecated": True},
)
_document(
    modbus_slave_resp_schema,
    "A Modbus unit and its scan.",
    [
        {
            "dev": "modbus_slave",
            "circuit": "1",
            "slave_id": 1,
            "modbus_type": "TCP",
            "modbus_spec": "127.0.0.1",
            "scan_interval": 0.02,
            "scan_enabled": True,
            "last_comm": 0.027,
            "scan_error": None,
            "comm": "ok",
        },
    ],
    modbus_type={"enum": ["TCP", "RTU"]},
    modbus_spec={
        "description": "The host of a Modbus TCP unit or the serial port of a Modbus RTU unit.",
        "examples": ["127.0.0.1", "/dev/ttyNS0"],
    },
    scan_error={
        "description": "The error of the last scan, null after a successful one. The scan of a failing "
        "unit is slowed down up to 16 s.",
        "examples": ["RequestRetryFailedError: Failed to get a valid response after 2 attempts", None],
    },
)
_document(
    device_info_resp_schema,
    "The controller or a unit, as described by the configuration.",
    [
        {"dev": "device_info", "family": "Patron", "model": "S167", "sn": 81, "board_count": 1, "circuit": "S167"},
    ],
    family={"examples": ["Patron", "Neuron", "UNIPI1"]},
    model={"examples": ["S103", "S167", "L533"]},
)
_document(
    serial_bus_resp_schema,
    "The configuration of a Modbus RTU bus, read-only.",
    [
        {
            "dev": "serial_bus",
            "circuit": "RS485_1",
            "port": "/dev/ttyNS0",
            "baudrate": 19200,
            "parity": "N",
            "stopbits": 1,
            "timeout": 0.5,
            "retries": 0,
            "probe_timeout": 0.1,
            "devices": ["xS51"],
        },
    ],
)
_document(
    tcp_bus_resp_schema,
    "The configuration of a Modbus TCP bus, read-only.",
    [
        {
            "dev": "tcp_bus",
            "circuit": "LOCAL_TCP",
            "hostname": "127.0.0.1",
            "port": 502,
            "timeout": 1.0,
            "connect_timeout": 2.0,
            "retries": 0,
            "probe_timeout": 1.0,
            "devices": ["1", "2"],
        },
    ],
)
_document(
    sequencer_resp_schema,
    "The running pulse or sequence of an output (RO, DO, LED), read-only; the circuit "
    "is the type and the circuit of the output.",
    [
        {
            "dev": "sequencer",
            "circuit": "do_1_01",
            "output": {"dev": "do", "circuit": "1_01"},
            "running": True,
            "name": "pulse",
            "step": 0,
            "steps": 1,
        },
        {
            "dev": "sequencer",
            "circuit": "ro_2_01",
            "output": {"dev": "ro", "circuit": "2_01"},
            "running": False,
            "name": None,
            "step": None,
            "steps": None,
        },
    ],
    running={"description": "A pulse or a sequence is running, the former *pending* of the output."},
    name={"examples": ["pulse", "sequence", None]},
)
_document(
    run_resp_schema,
    "The aliases, see [Aliases](" + _DOCS + "/configs/aliases/).",
    [
        {
            "dev": "run",
            "circuit": "alias",
            "save": False,
            "aliases": {"light_living_room": {"circuit": "ro_1_01", "devtype": "ro"}},
        },
    ],
    save={"description": "Always false, a save is requested by the params."},
    aliases={
        "description": "The aliases of the registered devices by their name, with the type and the circuit "
        "(`<type>_<circuit>`) of the device; an alias of a device which is not registered (e.g. of an offline "
        "Modbus unit) is not listed."
    },
)
