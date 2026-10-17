""" The HW definitions of the repository (hw_definitions/) as Evok loads them for a Modbus unit """
import logging
from pathlib import Path

import pytest
import yaml
from conftest import make_client, scan

from evok.config import HWDict
from evok.modbus.builder import IOParser

HW_DIR = Path(__file__).resolve().parent.parent / 'hw_definitions'
DEFINITIONS = sorted(HW_DIR.glob('*/*.yaml'))


def test_definitions_are_found():
    assert len(DEFINITIONS) > 30


def test_names_are_unique():
    """ A model is found by the name of its file in all directories, a duplicate would replace the other """
    names = [path.stem for path in DEFINITIONS]
    assert len(names) == len(set(names))
    definitions = HWDict(dir_paths=[str(d) for d in sorted({p.parent for p in DEFINITIONS})]).definitions
    assert set(definitions) == set(names)


@pytest.mark.parametrize('path', DEFINITIONS, ids=lambda p: f'{p.parent.name}/{p.name}')
async def test_definition(path, caplog):
    """ The unit of the definition is created without an error or a warning, e.g. a deprecated key,
        and every register read by its devices is in a register block
    """
    hw = yaml.safe_load(path.read_text())
    caplog.set_level(logging.WARNING, logger='evok')
    # the mode registers of the fake unit have the value of the first mode, not the unknown 0;
    # each AI has its mode register, the AOs of a feature share one
    holding = {}
    for feature in hw['modbus_features']:
        modes = feature.get('modes')
        if 'mode_reg' in feature and isinstance(modes, dict) and 'value' in next(iter(modes.values())):
            count = feature.get('count', 1) if feature['type'] == 'AI' else 1
            for i in range(count):
                holding[feature['mode_reg'] + i] = next(iter(modes.values()))['value']
    client = make_client(hw['modbus_register_blocks'], holding=holding)
    IOParser(client, hw['modbus_features'], 'x').populate()
    assert client.devices, 'no device'
    # the registers which the devices read are in the cache after the first scan
    await scan(client, initial=True)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not messages, messages
