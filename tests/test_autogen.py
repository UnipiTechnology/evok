""" evok-autogen.py: the configuration of the local units by the product """
import importlib.util
import io
from pathlib import Path

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location(
    'evok_autogen', Path(__file__).parent.parent / 'hw_definitions' / 'evok-autogen.py')
autogen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(autogen)


def devices(product_id):
    config = autogen.generate_config(autogen.hw_data[product_id], {}, False, 'Patron', 'X', 1, [])
    stream = io.StringIO()
    autogen.yaml_dump(config, stream, 0)
    # the file read by Evok
    return yaml.safe_load(stream.getvalue())['comm_channels']['LOCAL_TCP'].get('devices', {})


@pytest.mark.parametrize('product_id, ports', [
    (0x0407, {1: ['/dev/ttyNS0'], 2: ['/dev/ttyNS1']}),                        # M527
    (0x0903, {1: ['/dev/ttyNS0'], 2: ['/dev/ttyNS1'], 3: ['/dev/ttyNS2']}),    # L533
    (0x0F03, {1: ['/dev/ttyNS0'], 2: ['/dev/ttyNS1'], 3: None}),               # L503, E14DI14RO without a port
    (0x0303, {1: ['/dev/ttyNS0'], 2: None}),                                   # M203
    (0x0103, {1: ['/dev/ttyNS0']}),                                            # S103
    (0x0207, {1: None}),                                                       # S207, E8DI8DO
    (0x1007, {1: ['/dev/ttyNS0'], 2: ['/dev/ttyNS1']}),                        # M537, E8AI4DI5RO
])
def test_serial_ports_of_the_boards(product_id, ports):
    """ BRAIN, E4AI4AO4DI5RO, E4AI4AO6DI5RO and E8AI4DI5RO serve a serial port ttyNSx, x by their order from 0 """
    assert {name: device.get('serial_ports') for name, device in devices(product_id).items()} == ports


def test_model_is_a_string():
    assert devices(0x0407)[1]['model'] == '00'
