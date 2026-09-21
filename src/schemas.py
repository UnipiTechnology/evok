'''
Created on 16 Oct 2017

'''
from typing import Dict, Tuple
SCHEMA = "http://json-schema.org/draft/2020-12/schema"

owire_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "OW_sensor",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "interval": {"type": ["string", "number"]},
        "alias": {"type": "string"}
    }
}

owire_post_inp_example = {}

led_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Led",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": { "type": ["boolean", "string", "number"] },
        "alias": {"type": "string"}
    },
}

led_post_inp_example = {"value": '1'}

relay_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Relay",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": { "type": ["boolean", "string", 'number'] },
        "mode": {"type": "string"},
        "timeout": {"type": "string"},
        "pwm_freq": {"type": ["number", "string"]},
        "pwm_duty": {"type": ["number", "string"]},
        "alias": {"type": "string"}
    },
}

relay_post_inp_example = {"value": "1"}

ao_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_Output",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["string", "number"],
            "minimum": 0
        },
        "mode": {
            "type": "string",
            "enum": [
                "Voltage",
                "Current",
                "Resistance"
            ]
        },
        "alias": {
            "type": "string"
        },
        "frequency": {
            "description": "Only for the UniPi 1.1"
        }
    }
}

ao_post_inp_example = {"value": 1}

ai_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Analog_Input",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {
            "type": "string",
            "description": "Must be in 'modes'!"
        },
        "alias": {
            "type": "string"
        }
    }
}

ai_post_inp_example = {"mode": "Voltage"}

di_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Digital_Input",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "counter": {
            "type": ["number", "string"],
            "minimum": 0,
            "maximum": 4294967295
        },
        "counter_mode": {},
        "debounce": {"type": ["number", "string"]},
        "mode": {"type": "string"},
        "ds_mode": {"type": "string"},
        "alias": {"type": "string"}
    },
}

di_post_inp_example = {"value": 1}

register_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Modbus_register",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": "number",
            "minimum": 0,
            "maximum": 65535
        },
        "alias": {
            "type": "string"
        }
    }
}

register_post_inp_example = {"value": '1'}

wd_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "Master_Watchdog",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "value": {
            "type": ["string", "number"]
        },
        "timeout": {
            "type": ["string", "number"]
        },
        "reset": {
            "type": ["string", "number"]
        },
        "nv_save": {
            "type": ["string", "number"]
        },
        "alias": {
            "type": "string"
        }
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
            "type": "boolean"
        },
        "do_reset": {
            "type": "boolean"
        },
        "interval": {
            "type": ["number", "string"]
        },
        "scan_interval": {
            "type": ["number", "string"]
        },
        "circuit": {
            "type": "string"
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
    }
}

owpower_post_inp_example = {"value": True}

run_post_inp_schema = {
    "$schema": SCHEMA,
    "title": "running_evok_config",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "save": {
            "type": ["string", "number", "boolean"]
        },
    }
}

run_post_inp_example = {"save": True}


schemas: Dict[str, Tuple[dict, dict]] = {
    'input': (di_post_inp_schema, di_post_inp_example),
    'output': (relay_post_inp_schema, relay_post_inp_example),
    'register': (register_post_inp_schema, register_post_inp_example),
    'ai': (ai_post_inp_schema, ai_post_inp_example),
    'ao': (ao_post_inp_schema, ao_post_inp_example),
    'led': (led_post_inp_schema, led_post_inp_example),
    'watchdog': (wd_post_inp_schema, wd_post_inp_example),
    '1wdevice': (owire_post_inp_schema, owire_post_inp_example),
    'owbus': (owbus_post_inp_schema, owbus_post_inp_example),
    'owpower': (owpower_post_inp_schema, owpower_post_inp_example),
    'run': (run_post_inp_schema, run_post_inp_example),
}
schemas['di'] = schemas['input']
schemas['do'] = schemas['output']
schemas['relay'] = schemas['output']
schemas['analoginput'] = schemas['ai']
schemas['analogoutput'] = schemas['ao']
schemas['wd'] = schemas['watchdog']
schemas['temp'] = schemas['1wdevice']
schemas['sensor'] = schemas['1wdevice']
