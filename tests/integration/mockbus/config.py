"""Generate an Evok config pointing at the mockbus.

Evok reads /etc/evok/config.yaml (or a path override via ``-c``). For the
functional tier we generate a minimal config that:
  * listens on a test HTTP port (default 8090 to avoid clashes)
  * points comm_channels at the mockbus Modbus TCP server (127.0.0.1:5020)
  * declares the two-board Neuron M103 exactly as the real device:
      slave-id 1 -> model "00" (CPU board: 4 DI, 4 DO, 1 AI, 1 AO, 4 LED, WD, owpower)
      slave-id 2 -> model "01" (relay board: 8 DI, 8 RO, 1 WD)
  * advertises device_info (family/model/board_count) so /rest/all lists it
  * enables the websocket API

The hw_definition files (``00.yaml``, ``01.yaml``) are those of the repository,
``hw_definitions/neuron/``.

The 1-Wire bus (OWBUS / temp sensor) is configured as an OWFS bus, but it is not
served by a daemon: evok reads the kernel 1-Wire subsystem directly. The launcher
(``start.py``) mounts a fake sysfs tree at ``/sys/bus/w1/devices`` in a private
mount namespace, so the sensor tests have a target without hardware.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent / "run"


def generate_config(
    http_port: int = 8090,
    modbus_port: int = 5020,
    modbus_host: str = "127.0.0.1",
) -> Path:
    """Write a test evok config; return its path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {
        "autogen": False,
        "logging": {"level": "WARNING"},
        "apis": {
            "port": http_port,
            "address": "127.0.0.1",
            "websocket": {"enabled": True, "all_filtered": False},
        },
        "comm_channels": {
            "MOCKBUS": {
                "type": "MODBUSTCP",
                "hostname": modbus_host,
                "port": modbus_port,
                "device_info": {
                    "family": "Neuron",
                    "model": "M103",
                    "sn": 0,
                    "board_count": 2,
                },
                "devices": {
                    "1": {"slave-id": 1, "model": "00"},
                    "2": {"slave-id": 2, "model": "01"},
                },
            },
            # 1-Wire bus: evok reads the kernel subsystem at /sys/bus/w1/devices.
            # The launcher mounts a fake sysfs tree there (a DS18B20 at the same
            # address the cassettes were recorded against). owpower '1' is the
            # OwPower device registered from board 1's hw_definition (val_coil
            # 1001) and is driven by the mockbus; the fake bus does not need it
            # (it never powers down the bus), but evok requires the circuit to
            # resolve for `do_reset`.
            "OWBUS": {
                "type": "OWFS",
                "master": "w1_bus_master1",
                "interval": 3,
                "scan_interval": 60,
                "owpower": "1",
            },
        },
    }
    path = CONFIG_DIR / "config.yaml"
    path.write_text(yaml.dump(cfg, sort_keys=False))
    return path
