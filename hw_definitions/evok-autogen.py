#!/usr/bin/python3
import os
import subprocess
from typing import List, Union

OWFS_CONFIG_PATH = "/etc/owfs.conf"
UNIPITCP_CONFIG_PATH = "/etc/default/unipitcp"

BRAIN = "00"
E14DI14RO = "09"
E16DI14DI = "0A"
E16DI14RO = "08"
E14RO14RO = "07"
E8DI8DO = "01"
E4AI4AO4DI5RO = "13"
E4AI4AO6DI5RO = "0F"
E8AI4DI5RO = "30"

UNIPI11 = "UNIPI11"
UNIPI11LITE = "UNIPI11LITE"

class LED_PROXY:
    E410 = "L0306"
    E411 = "L0406"
    E412 = "L0506"
    E413 = "L0606"

card_models = []


def read_envs(path: str) -> dict[str, str]:
    ret = dict()
    with open(path, 'r') as f:
        for line in f.readlines():
            while " " in line:
                line = line.replace(" ", "")
            if not line.startswith("#") and line.count("=") == 1:
                key, value = line.replace('\n', '').split("=")
                ret[key] = value
    return ret



def get_iris_card_data(card_info: str) -> (None | str, None | dict):
    """
    :param card_info: Info about card from os configurator.
    """
    global card_models
    card_id, slot_id = card_info.split("__")
    slot_id = int(slot_id)

    # get card data
    stdout, stderr = subprocess.Popen(f"/opt/unipi/tools/unipiid card_description.{slot_id}", shell=True,
                                      stdout=subprocess.PIPE).communicate()
    cd = {
        cd.split(":")[0]: cd.split(":")[1].replace(' ', '')
        for cd in stdout.decode().split("\n")
        if ":" in cd
    }

    # check device model
    model_name = cd['Model']
    available_models = [m[:-5] for m in os.listdir("/etc/evok/hw_definitions") if m.endswith(".yaml")]
    if model_name not in available_models:
        return None, None

    card_models.append(model_name)
    return slot_id, {
        'slave-id': slot_id,
        'model': model_name,
        'device_info': {
            'family': "Iris",
            'model': cd['Model'],
            # 'sn': int(cd['Serial']),
        }
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
    0x0a03: [BRAIN],  # S103_G
    0x0b03: [BRAIN, E14RO14RO],  # M403
    0x0c03: [BRAIN, E4AI4AO6DI5RO],  # M503
    # 0x0d03: [BRAIN],  # M603
    0x0e03: [BRAIN, E16DI14DI, E16DI14DI],  # L303
    0x0F03: [BRAIN, E4AI4AO6DI5RO, E14DI14RO],  # L503
    0x1003: [BRAIN, E4AI4AO6DI5RO, E4AI4AO6DI5RO],  # L513

    0x0107: [BRAIN],  # S107
    0x0707: [BRAIN],  # S117
    0x0a07: [BRAIN],  # S167
    0x0d07: [BRAIN],  # S167_2
    0x0207: [E8DI8DO],  # S207
    0x0b07: [E8DI8DO],  # S227
    0x0307: [BRAIN, E16DI14RO],  # M207
    0x0407: [BRAIN, E4AI4AO4DI5RO],  # M527
    0x0507: [BRAIN, E16DI14RO, E16DI14RO],  # L207
    0x0607: [BRAIN, E4AI4AO4DI5RO, E16DI14RO],  # L527
    0x0807: [BRAIN, E16DI14RO],  # M267
    0x0e07: [BRAIN, E16DI14RO],  # M267_2
    0x0907: [BRAIN, E4AI4AO4DI5RO],  # M567
    0x0f07: [BRAIN, E4AI4AO4DI5RO],  # M567_2
    0x1007: [BRAIN, E8AI4DI5RO],  # M537

    0x0001: [UNIPI11],  # UNIPI10
    0x0101: [UNIPI11],  # UNIPI11
    0x1101: [UNIPI11LITE],  # UNIPI11LITE

    0x0306: [LED_PROXY.E410], #  E410
    0x0406: [LED_PROXY.E411], # E411
    0x0506: [LED_PROXY.E412], # E412
    0x0606: [LED_PROXY.E413], # E413

}

code2family = {
    1: 'UNIPI1',
    2: 'Gate',
    3: 'Neuron',
    6: 'Edge',
    7: 'Patron',
    15: 'Iris',
}


def configure_owfs(family: str):
    owfs_config_lines = [
        "### CONFIGURED BY EVOK ###",
        f"server: i2c=/dev/i2c-{'1' if family in ['Neuron', 'UNIPI1'] else '2'}",
        "server: w1",
        "##########################"
    ]

    change = False
    required_lines = list(owfs_config_lines)
    lines = list()
    if os.path.isfile(OWFS_CONFIG_PATH):
        with open(OWFS_CONFIG_PATH, 'r') as f:
            while True:
                line = f.readline()
                if len(line) == 0:
                    break
                line = line.replace('\n', '')
                if line in required_lines:
                    required_lines.remove(line)
                    if line == owfs_config_lines[0]:
                        return  # If have signature by evok, do nothing.
                if 'FAKE' in line and '#' != line.replace(' ', '')[0]:
                    line = '#' + line
                    change = True
                lines.append(line)

    if len(required_lines) > 0 or change:
        if len(required_lines) > 0:
            lines.append('\n')
            lines.extend(required_lines)
        with open(OWFS_CONFIG_PATH, 'w') as f:
            for line in lines:
                f.write(f"{line}\n")
        print("Configured OWFS")


def generate_config(boards: List[str], defaults: Union[None, dict], has_ow: bool,
                    family: str, product_model: str, product_serial: int, cards: List[str]):
    defaults = defaults if defaults is not None else dict()
    port = defaults.get('port', 502)
    hostname = defaults.get('hostname', '127.0.0.1')
    names = defaults.get('names', [i for i in range(1, len(boards) + 1)])
    slave_ids = defaults.get('slave-ids', [i for i in range(1, len(boards) + 1)])

    ret = {
        'comm_channels': {
            'LOCAL_TCP': {
                'type': 'MODBUSTCP',
                'hostname': hostname,
                'port': port,
                'device_info': {
                    'family': family,
                    'model': product_model,
                    'sn': product_serial,
                    'board_count': len(boards)
                },
            }
        }
    }

    if len(boards) > 0 or len(cards) > 0:
        ret['comm_channels']['LOCAL_TCP']['devices'] = {}
        if len(boards) > 0:
            for i in range(len(boards)):
                ret['comm_channels']['LOCAL_TCP']['devices'][names[i]] = {
                    'slave-id': slave_ids[i],
                    'model': f"'{boards[i]}'"
                }

    if family == "UNIPI1":
        for card in cards:
            device, slot = card.split('__')
            if device == "0018":
                ret['comm_channels']['LOCAL_TCP']['devices'][int(slot) + 1] = {
                    'slave-id': slot,
                    'model': 'EMO-R8'
                }
    elif family == "Iris":
        for card in cards:
            card_slot, card_data = get_iris_card_data(card)
            if card_slot is not None and card_data is not None:
                ret['comm_channels']['LOCAL_TCP']['devices'][card_slot] = card_data

    if has_ow:
        ret['comm_channels']['OWBUS'] = {
            'type': 'OWFS',
            'interval': 10,
            'scan_interval': 60,
        }
        if BRAIN in boards:
            ret['comm_channels']['OWBUS']['owpower'] = 1

    return ret


def yaml_dump(data: dict, stream, depth: int):
    pre = ''.join(['  ' for i in range(depth)])
    for key, value in data.items():
        if type(value) is dict:
            stream.write(f"{pre}{key}:\n")
            yaml_dump(value, stream, depth + 1)
        else:
            stream.write(f"{pre}{key}: {value}\n")


def run():
    try:
        envs = os.environ
        platform_id = int(envs['UNIPI_PRODUCT_ID'], 16)
        family = code2family.get(int(str(envs['UNIPI_PRODUCT_ID'])[2:], 16), 'UNKNOWN')
        product_model = envs.get("UNIPI_PRODUCT_NAME", "UNKNOWN")
        product_serial = envs.get("UNIPI_PRODUCT_SERIAL", "UNKNOWN")
        has_ow = bool(int(envs.get('HAS_DS2482', '0')))
        cards: List[str] = envs.get('CARDS', '').split()
        boards: List[str] = hw_data.get(platform_id, [])
    except Exception as E:
        print(f"Device not recognized!  ({E})")
        exit(0)

    is_unipi_one = True if platform_id in [0x0001, 0x0101, 0x1101] else False

    if has_ow:
        configure_owfs(family)

    defaults = dict()

    if is_unipi_one:
        defaults['port'] = 50200
        defaults['slave-ids'] = [0]

    elif family == "Edge":
        defaults['slave-ids'] = [0, 1]

    if os.path.isfile(UNIPITCP_CONFIG_PATH):
        envs = read_envs(UNIPITCP_CONFIG_PATH)
        if "LISTEN_PORT" in envs:
            defaults['port'] = envs['LISTEN_PORT']
        if "LISTEN_IP" in envs and envs['LISTEN_IP'] != "0.0.0.0":
            defaults['hostname'] = envs['LISTEN_IP']

    autogen_conf = generate_config(boards, defaults=defaults, has_ow=has_ow,
                                   family=family, product_model=product_model, product_serial=product_serial,
                                   cards=cards)

    msg = f"Detect device {family} {product_model} (id={hex(platform_id)}, sn={product_serial})"
    if len(boards):
        msg += f" with boards {boards}"
    if len(card_models):
        msg += f" with cards {card_models}"
    print(msg)

    with open('/etc/evok/autogen.yaml', 'w') as f:
        yaml_dump(data=autogen_conf, stream=f, depth=0)


if __name__ == '__main__':
    run()
