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
            "circuit": {"type": "string", "description": 'Device circuit (or "all").', "readOnly": True},
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
