#!/usr/bin/python3
"""Generate autogen.yaml of Evok, the configuration of the local units of the Unipi controller

The product is given by the environment of unipi-os-configurator (UNIPI_PRODUCT_ID, UNIPI_PRODUCT_NAME,
UNIPI_PRODUCT_SERIAL, HAS_DS2482, CARDS), the product id also by --product-id.
"""

import argparse
import os
import subprocess

UNIPITCP_CONFIG_PATH = "/etc/default/unipitcp"
CONFIG_DIR = "/etc/evok"  # the directory of autogen.yaml and hw_definitions, --config-dir
MODBUS_PORT = 50200  # the Modbus TCP server of the Unipi OS, LISTEN_PORT of UNIPITCP_CONFIG_PATH

BRAIN = "00"
E14DI14RO = "09"
E16DI14DI = "0A"
E16DI14RO = "08"
E14RO14RO = "07"
E8DI8DO = "01"
E4AI4AO4DI5RO = "13"
E4AI4AO6DI5RO = "0F"
E8AI4DI5RO = "30"

# the boards which serve a serial port ttyNSx too, x by their order from 0; a request on the port corrupts
# the NV save of the board (a bug of the firmware), Evok holds the bus of the port by serial_ports
SERIAL_PORT_BOARDS = (BRAIN, E4AI4AO4DI5RO, E4AI4AO6DI5RO, E8AI4DI5RO)

UNIPI11 = "UNIPI11"
UNIPI11LITE = "UNIPI11LITE"


class LED_PROXY:
    E410 = "L0306"
    E411 = "L0406"
    E412 = "L0506"
    E413 = "L0606"


card_models = []


def read_envs(path: str) -> dict[str, str]:
    ret = {}
    with open(path) as f:
        for line in f.readlines():
            while " " in line:
                line = line.replace(" ", "")
            if not line.startswith("#") and line.count("=") == 1:
                key, value = line.replace("\n", "").split("=")
                ret[key] = value
    return ret


def get_iris_card_data(card_info: str, config_dir: str = CONFIG_DIR) -> (str | None, dict | None):
    """
    :param card_info: Info about card from os configurator.
    :param config_dir: the directory with hw_definitions, the card is used if its model has a definition
    """
    global card_models
    _card_id, slot_id = card_info.split("__")
    slot_id = int(slot_id)

    # get card data
    stdout, _stderr = subprocess.Popen(
        f"/opt/unipi/tools/unipiid card_description.{slot_id}", shell=True, stdout=subprocess.PIPE
    ).communicate()
    cd = {cd.split(":")[0]: cd.split(":")[1].replace(" ", "") for cd in stdout.decode().split("\n") if ":" in cd}

    # check device model
    model_name = cd["Model"]
    available_models = [m[:-5] for m in os.listdir(os.path.join(config_dir, "hw_definitions")) if m.endswith(".yaml")]
    if model_name not in available_models:
        return None, None

    card_models.append(model_name)
    return slot_id, {
        "slave-id": slot_id,
        "model": model_name,
        "device_info": {
            "family": "Iris",
            "model": cd["Model"],
            # 'sn': int(cd['Serial']),
        },
    }


hw_data = {
    0x0103: [BRAIN],  # S103
    0x1103: [BRAIN],  # S103_E
    0x1203: [BRAIN],  # S103_I
    0x0203: [BRAIN, E8DI8DO],  # M103
    0x0303: [BRAIN, E16DI14RO],  # M203
    0x0403: [BRAIN, E16DI14DI],  # M303
    0x0503: [BRAIN, E4AI4AO4DI5RO],  # M523
    0x0603: [BRAIN, E16DI14RO, E16DI14RO],  # L203
    0x0703: [BRAIN, E14RO14RO, E14RO14RO],  # L403
    0x0803: [BRAIN, E4AI4AO4DI5RO, E16DI14RO],  # L523
    0x0903: [BRAIN, E4AI4AO4DI5RO, E4AI4AO4DI5RO],  # L533
    0x0A03: [BRAIN],  # S103_G
    0x0B03: [BRAIN, E14RO14RO],  # M403
    0x0C03: [BRAIN, E4AI4AO6DI5RO],  # M503
    # 0x0d03: [BRAIN],  # M603
    0x0E03: [BRAIN, E16DI14DI, E16DI14DI],  # L303
    0x0F03: [BRAIN, E4AI4AO6DI5RO, E14DI14RO],  # L503
    0x1003: [BRAIN, E4AI4AO6DI5RO, E4AI4AO6DI5RO],  # L513
    0x0107: [BRAIN],  # S107
    0x0707: [BRAIN],  # S117
    0x0A07: [BRAIN],  # S167
    0x0D07: [BRAIN],  # S167_2
    0x0207: [E8DI8DO],  # S207
    0x0B07: [E8DI8DO],  # S227
    0x0307: [BRAIN, E16DI14RO],  # M207
    0x0407: [BRAIN, E4AI4AO4DI5RO],  # M527
    0x0507: [BRAIN, E16DI14RO, E16DI14RO],  # L207
    0x0607: [BRAIN, E4AI4AO4DI5RO, E16DI14RO],  # L527
    0x0807: [BRAIN, E16DI14RO],  # M267
    0x0E07: [BRAIN, E16DI14RO],  # M267_2
    0x0907: [BRAIN, E4AI4AO4DI5RO],  # M567
    0x0F07: [BRAIN, E4AI4AO4DI5RO],  # M567_2
    0x1007: [BRAIN, E8AI4DI5RO],  # M537
    0x0001: [UNIPI11],  # UNIPI10
    0x0101: [UNIPI11],  # UNIPI11
    0x1101: [UNIPI11LITE],  # UNIPI11LITE
    0x0306: [LED_PROXY.E410],  #  E410
    0x0406: [LED_PROXY.E411],  # E411
    0x0506: [LED_PROXY.E412],  # E412
    0x0606: [LED_PROXY.E413],  # E413
}

code2family = {
    1: "UNIPI1",
    2: "Gate",
    3: "Neuron",
    6: "Edge",
    7: "Patron",
    15: "Iris",
}


def generate_config(
    boards: list[str],
    defaults: dict | None,
    has_ow: bool,
    family: str,
    product_model: str,
    product_serial: int,
    cards: list[str],
    config_dir: str = CONFIG_DIR,
):
    defaults = defaults if defaults is not None else {}
    port = defaults.get("port", MODBUS_PORT)
    hostname = defaults.get("hostname", "127.0.0.1")
    names = defaults.get("names", list(range(1, len(boards) + 1)))
    slave_ids = defaults.get("slave-ids", list(range(1, len(boards) + 1)))

    ret = {
        "comm_channels": {
            "LOCAL_TCP": {
                "type": "MODBUSTCP",
                "hostname": hostname,
                "port": port,
                "device_info": {
                    "family": family,
                    "model": product_model,
                    "sn": product_serial,
                    "board_count": len(boards),
                },
            }
        }
    }

    if len(boards) > 0 or len(cards) > 0:
        ret["comm_channels"]["LOCAL_TCP"]["devices"] = {}
        if len(boards) > 0:
            serial_port = 0
            for i in range(len(boards)):
                device = {
                    "slave-id": slave_ids[i],
                    "model": f"'{boards[i]}'",
                }
                if boards[i] in SERIAL_PORT_BOARDS:
                    device["serial_ports"] = f"[/dev/ttyNS{serial_port}]"
                    serial_port += 1
                ret["comm_channels"]["LOCAL_TCP"]["devices"][names[i]] = device

    if family == "UNIPI1":
        for card in cards:
            device, slot = card.split("__")
            if device == "0018":
                ret["comm_channels"]["LOCAL_TCP"]["devices"][int(slot) + 1] = {"slave-id": slot, "model": "EMO-R8"}
    elif family == "Iris":
        for card in cards:
            card_slot, card_data = get_iris_card_data(card, config_dir)
            if card_slot is not None and card_data is not None:
                ret["comm_channels"]["LOCAL_TCP"]["devices"][card_slot] = card_data

    if has_ow:
        # read by the kernel (w1), the DS2482 of the unit is bound to its driver by the device tree;
        # without 'master' the bus uses the first master of the kernel
        ret["comm_channels"]["OWBUS"] = {
            "type": "OWFS",
            "interval": 10,
            "scan_interval": 60,
        }
        if BRAIN in boards:
            ret["comm_channels"]["OWBUS"]["owpower"] = 1

    return ret


def yaml_dump(data: dict, stream, depth: int):
    pre = "".join(["  " for i in range(depth)])
    for key, value in data.items():
        if type(value) is dict:
            stream.write(f"{pre}{key}:\n")
            yaml_dump(value, stream, depth + 1)
        else:
            stream.write(f"{pre}{key}: {value}\n")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-d",
        "--config-dir",
        default=CONFIG_DIR,
        help=f"the directory of autogen.yaml and hw_definitions, e.g. of Evok in a virtual environment "
        f"(default {CONFIG_DIR})",
    )
    parser.add_argument(
        "-p",
        "--product-id",
        help="the product id in hex, e.g. 0407 or 0x0407 of the Patron M527, instead of UNIPI_PRODUCT_ID",
    )
    return parser.parse_args(argv)


def run(argv=None):
    args = parse_args(argv)
    try:
        envs = os.environ
        platform_id = int(args.product_id if args.product_id is not None else envs["UNIPI_PRODUCT_ID"], 16)
        # the low byte is the family, e.g. 0x07 of the Patron
        family = code2family.get(platform_id & 0xFF, "UNKNOWN")
        product_model = envs.get("UNIPI_PRODUCT_NAME", "UNKNOWN")
        product_serial = envs.get("UNIPI_PRODUCT_SERIAL", "UNKNOWN")
        has_ow = bool(int(envs.get("HAS_DS2482", "0")))
        cards: list[str] = envs.get("CARDS", "").split()
        boards: list[str] = hw_data.get(platform_id, [])
    except (KeyError, ValueError) as E:  # a missing or invalid variable of the product
        print(f"Device not recognized!  ({E})")
        exit(0)

    is_unipi_one = platform_id in [0x0001, 0x0101, 0x1101]

    defaults = {}

    if is_unipi_one:
        defaults["slave-ids"] = [0]

    elif family == "Edge":
        defaults["slave-ids"] = [0, 1]

    if os.path.isfile(UNIPITCP_CONFIG_PATH):
        envs = read_envs(UNIPITCP_CONFIG_PATH)
        if "LISTEN_PORT" in envs:
            defaults["port"] = envs["LISTEN_PORT"]
        if "LISTEN_IP" in envs and envs["LISTEN_IP"] != "0.0.0.0":
            defaults["hostname"] = envs["LISTEN_IP"]

    autogen_conf = generate_config(
        boards,
        defaults=defaults,
        has_ow=has_ow,
        family=family,
        product_model=product_model,
        product_serial=product_serial,
        cards=cards,
        config_dir=args.config_dir,
    )

    msg = f"Detect device {family} {product_model} (id={hex(platform_id)}, sn={product_serial})"
    if len(boards):
        msg += f" with boards {boards}"
    if len(card_models):
        msg += f" with cards {card_models}"
    print(msg)

    with open(os.path.join(args.config_dir, "autogen.yaml"), "w") as f:
        yaml_dump(data=autogen_conf, stream=f, depth=0)


if __name__ == "__main__":
    run()
