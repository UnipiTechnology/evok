""" JSON schemas of the params of set() of the device types, used by REST, bulk and WebSocket """
SCHEMA = "https://json-schema.org/draft/2020-12/schema"

# 7: the name of the alias is checked by Aliases.validate(), the length here
MAX_ALIAS_LENGTH = 64
ALIAS = {"type": "string", "maxLength": MAX_ALIAS_LENGTH}

owire_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_sensor",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "interval": {"type": ["string", "number"]},
        "alias": ALIAS
    }
}

owire_post_inp_example = {"interval": 15}

led_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Led",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", "number"]},
        "pulse_duration": {"type": ["number", "string"], "minimum": 0},   # 0 is rejected by the device
        "alias": ALIAS
    },
}

led_post_inp_example = {"value": '1'}

relay_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Relay",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", 'number']},
        "pulse_duration": {"type": ["number", "string"], "minimum": 0},   # 0 is rejected by the device
        "alias": ALIAS
    },
}

relay_post_inp_example = {"value": "1"}

do_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Digital_output",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {"type": ["boolean", "string", 'number']},
        "mode": {"type": "string"},
        "pulse_duration": {"type": ["number", "string"], "minimum": 0},   # 0 is rejected by the device
        "timeout": {"type": ["number", "string"], "minimum": 0},          # deprecated alias of pulse_duration
        "pwm_freq": {"type": ["number", "string"], "minimum": 0},     # 0 is rejected by the device
        "pwm_duty": {"type": ["number", "string"], "minimum": 0, "maximum": 100},
        "alias": ALIAS
    },
}

do_post_inp_example = {"value": "1"}

ao_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_output",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["string", "number"],
            "minimum": 0
        },
        "mode": {
            "type": "string",
            "description": "Must be in 'modes', they are given by the hardware definition"
        },
        "alias": ALIAS
    }
}

ao_post_inp_example = {"value": 1}

ai_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_input",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {
            "type": "string",
            "description": "Must be in 'modes'!"
        },
        "alias": ALIAS
    }
}

ai_post_inp_example = {"mode": "Voltage"}

di_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Digital_input",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "counter": {
            "type": ["number", "string"],
            "minimum": 0,
            "maximum": 4294967295
        },
        "counter_mode": {"type": "string"},
        "debounce": {"type": ["number", "string"], "minimum": 0, "maximum": 65535},
        "mode": {"type": "string"},
        "ds_mode": {"type": "string"},
        "alias": ALIAS
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
            "maximum": 65535
        },
        "alias": ALIAS
    }
}

register_post_inp_example = {"value": '1'}

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
            "examples": [21.5, "21.5"]
        },
        "alias": {
            **ALIAS,
            "description": "Alias of the data point",
            "examples": ["setpoint_living_room"]
        }
    }
}

data_point_post_inp_example = {"value": 21.5}

wd_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Watchdog",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["boolean", "string", "number"]
        },
        "timeout": {
            "type": ["string", "number"],
            "minimum": 0
        },
        "reset": {
            "type": ["boolean", "string", "number"]
        },
        "nv_save": {
            "type": ["boolean", "string", "number"]
        },
        "alias": ALIAS
    }
}

wd_post_inp_example = {"value": '1'}

owbus_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_bus",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "do_scan": {
            "type": ["boolean", "number", "string"]   # a form of REST sends strings, converted by to_bool()
        },
        "do_reset": {
            "type": ["boolean", "number", "string"]
        },
        "interval": {
            "type": ["number", "string"]
        },
        "scan_interval": {
            "type": ["number", "string"]
        }
    }
}

owbus_post_inp_example = {"do_reset": True, "do_scan": True}

owpower_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OneWire_power",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["number", "string", "boolean"]
        },
        "alias": ALIAS
    }
}

owpower_post_inp_example = {"value": True}

run_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Aliases",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "save": {
            "type": ["string", "number", "boolean"]
        },
        "delete": {
            "type": "string",
            "description": "Alias to delete, also an alias of a device which is not registered (e.g. offline)"
        },
    }
}

run_post_inp_example = {"save": True}

nv_save_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "NV_save",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["number", "string", "boolean"]
        },
        "alias": ALIAS
    }
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
                    "device_circuits": _bulk_circuits
                }
            }
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
                    "device_circuits": _bulk_circuits
                }
            }
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
                    "assigned_values": {"type": "object"}  # checked by the schema of the device_type
                }
            }
        }
    }
}

bulk_post_inp_example = {
    "individual_assignments": [{"device_type": "do", "device_circuit": "1_01", "assigned_values": {"value": 1}}]
}


schemas: dict[str, tuple[dict, dict]] = {
    'input': (di_post_inp_schema, di_post_inp_example),
    'output': (do_post_inp_schema, do_post_inp_example),
    'ro': (relay_post_inp_schema, relay_post_inp_example),
    'register': (register_post_inp_schema, register_post_inp_example),
    'data_point': (data_point_post_inp_schema, data_point_post_inp_example),
    'ai': (ai_post_inp_schema, ai_post_inp_example),
    'ao': (ao_post_inp_schema, ao_post_inp_example),
    'led': (led_post_inp_schema, led_post_inp_example),
    'watchdog': (wd_post_inp_schema, wd_post_inp_example),
    '1wdevice': (owire_post_inp_schema, owire_post_inp_example),
    'owbus': (owbus_post_inp_schema, owbus_post_inp_example),
    'owpower': (owpower_post_inp_schema, owpower_post_inp_example),
    'run': (run_post_inp_schema, run_post_inp_example),
    'nv_save': (nv_save_post_inp_schema, nv_save_post_inp_example),
}
schemas['di'] = schemas['input']
schemas['digitalinput'] = schemas['input']
schemas['do'] = schemas['output']
schemas['digitaloutput'] = schemas['output']
schemas['relay'] = schemas['ro']
schemas['analoginput'] = schemas['ai']
schemas['analogoutput'] = schemas['ao']
schemas['wd'] = schemas['watchdog']
schemas['temp'] = schemas['1wdevice']
schemas['sensor'] = schemas['1wdevice']
