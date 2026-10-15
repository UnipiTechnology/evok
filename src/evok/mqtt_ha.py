"""Home Assistant MQTT discovery of the devices published by the MQTT API

The config of an entity is published retained to <ha_prefix>/<component>/<node>/<object_id>/config,
before the first state of the device; again when it changes, e.g. the alias (the name of the entity)
or the range of an AO in another mode. The entities read the states of the MQTT API by value templates,
the commands are its plain values on <prefix>/<device>/<circuit>/set. The entities of a Modbus unit
or of a 1-Wire bus are one device of Home Assistant, available by <prefix>/status and by comm of their state.
"""

import re

from .devices import AI, AO, DATA_POINT, DEVICE_INFO, DI, DO, LED, MODBUS_SLAVE, RO, SENSOR, Devices

VALUE = "{{ value_json.value }}"

# DS2438: the field of the state, its name, unit and device class
DS2438_FIELDS = (
    ("temp", "temperature", "°C", "temperature"),
    ("humidity", "humidity", "%", "humidity"),
    ("vdd", "VDD", "V", "voltage"),
    ("vad", "VAD", "V", "voltage"),
)


def ha_id(text) -> str:
    """An id of Home Assistant: letters, digits, '_' and '-'"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(text))


def _group(devtype, circuit, device) -> str | None:
    """The Modbus unit or the 1-Wire bus of the device, a device of Home Assistant"""
    if devtype == MODBUS_SLAVE:
        return str(circuit)
    if devtype == SENSOR:
        bus = getattr(device, "bus", None)
        return None if bus is None else str(bus.circuit)
    group = getattr(device, "major_group", None)
    return None if group in (None, "") else str(group)


def _ha_device(node: str, group: str) -> dict:
    ha_device = {"identifiers": [f"{node}_{ha_id(group)}"], "name": f"{node} {group}", "manufacturer": "Unipi"}
    info = Devices[DEVICE_INFO].get(group)
    if info is not None and getattr(info, "model", None) not in (None, "unknown"):
        ha_device["model"] = info.model
    return ha_device


def _entities(devtype, state: dict, read_only: bool) -> list[tuple[str, str, dict]]:
    """The entities of a device: (component, suffix of the object id, config without the common keys)"""
    dev = state.get("dev")
    if devtype == DI:
        return [("binary_sensor", "", {"value_template": VALUE, "payload_on": "1", "payload_off": "0"})]
    if devtype in (RO, DO, LED):
        if read_only:
            return [("binary_sensor", "", {"value_template": VALUE, "payload_on": "1", "payload_off": "0"})]
        return [
            (
                "switch",
                "",
                {
                    "value_template": VALUE,
                    "state_on": "1",
                    "state_off": "0",
                    "payload_on": "1",
                    "payload_off": "0",
                    "command": True,
                },
            )
        ]
    if devtype == AI:
        return [
            (
                "sensor",
                "",
                {"value_template": VALUE, "unit_of_measurement": state.get("unit"), "state_class": "measurement"},
            )
        ]
    if devtype == AO:
        if read_only:
            return [("sensor", "", {"value_template": VALUE, "unit_of_measurement": state.get("unit")})]
        low, high = state.get("range") or (0, 10)
        return [
            (
                "number",
                "",
                {
                    "value_template": VALUE,
                    "unit_of_measurement": state.get("unit"),
                    "min": low,
                    "max": high,
                    "step": 0.01,
                    "mode": "box",
                    "command": True,
                },
            )
        ]
    if devtype == DATA_POINT:
        config = {"value_template": VALUE, "unit_of_measurement": state.get("unit")}
        if state.get("writable") and not read_only:
            return [("number", "", dict(config, min=-1e9, max=1e9, step=0.001, mode="box", command=True))]
        return [("sensor", "", dict(config, state_class="measurement"))]
    if devtype == SENSOR and dev == "temp":
        return [
            (
                "sensor",
                "",
                {
                    "value_template": VALUE,
                    "unit_of_measurement": "°C",
                    "device_class": "temperature",
                    "state_class": "measurement",
                },
            )
        ]
    if devtype == SENSOR and state.get("type") == "DS2438":
        return [
            (
                "sensor",
                f"_{field}",
                {
                    "value_template": f"{{{{ value_json.{field} }}}}",
                    "unit_of_measurement": unit,
                    "device_class": device_class,
                    "state_class": "measurement",
                    "name_suffix": name,
                },
            )
            for field, name, unit, device_class in DS2438_FIELDS
        ]
    if devtype == MODBUS_SLAVE:
        return [
            (
                "binary_sensor",
                "",
                {
                    "value_template": "{{ 'ON' if value_json.scan_error is none else 'OFF' }}",
                    "device_class": "connectivity",
                    "name_suffix": "communication",
                },
            )
        ]
    return []


def _availability(prefix, devtype, state_topic, state) -> dict:
    """Evok online and the communication of the device ok, a device of a unit which does not respond
    is unavailable; the communication of a unit itself is available while Evok is online
    """
    status = {"topic": f"{prefix}/status", "payload_available": "online", "payload_not_available": "offline"}
    if "comm" not in state or devtype == MODBUS_SLAVE:
        return {"availability": [status]}
    comm = {
        "topic": state_topic,
        "value_template": "{{ 'online' if value_json.comm == 'ok' else 'offline' }}",
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    return {"availability": [status, comm], "availability_mode": "all"}


def discovery(
    prefix: str, ha_prefix: str, devtype: str, circuit, state: dict, read_only=False, device=None
) -> list[tuple[str, dict]]:
    """The config messages (topic, payload) of the entities of a device, none for an unsupported device"""
    if device is None:
        device = Devices[devtype].get(str(circuit))
    group = _group(devtype, circuit, device)
    if group is None:
        return []
    node = ha_id(prefix)
    state_topic = f"{prefix}/{devtype}/{circuit}"
    name = state.get("alias") or state.get("name") or f"{devtype.upper()} {circuit}"
    messages = []
    for component, suffix, config in _entities(devtype, state, read_only):
        config = dict(config)
        name_suffix = config.pop("name_suffix", None)
        object_id = ha_id(f"{devtype}_{circuit}{suffix}")
        payload = {
            "name": f"{name} {name_suffix}" if name_suffix else name,
            "unique_id": f"{node}_{object_id}",
            "state_topic": state_topic,
            **_availability(prefix, devtype, state_topic, state),
            "device": _ha_device(node, group),
        }
        if config.pop("command", False):
            payload["command_topic"] = f"{state_topic}/set"
        payload.update({key: value for key, value in config.items() if value is not None})
        messages.append((f"{ha_prefix}/{component}/{node}/{object_id}/config", payload))
    return messages
