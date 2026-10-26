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


@pytest.fixture
def product(monkeypatch, tmp_path):
    """ The environment of unipi-os-configurator without UNIPI_PRODUCT_ID, no config of the Modbus TCP server """
    monkeypatch.setattr(autogen, 'UNIPITCP_CONFIG_PATH', str(tmp_path / 'unipitcp'))
    monkeypatch.setattr(autogen, 'card_models', [])
    for name in ('UNIPI_PRODUCT_ID', 'UNIPI_PRODUCT_NAME', 'UNIPI_PRODUCT_SERIAL', 'HAS_DS2482', 'CARDS'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('UNIPI_PRODUCT_NAME', 'M527')


def written(config_dir):
    return yaml.safe_load((config_dir / 'autogen.yaml').read_text())['comm_channels']['LOCAL_TCP']


@pytest.mark.parametrize('product_id', ['0407', '0x0407'])
def test_product_id_and_config_dir_by_the_arguments(product, tmp_path, product_id):
    autogen.run(['--config-dir', str(tmp_path), '--product-id', product_id])
    local = written(tmp_path)
    assert local['device_info']['family'] == 'Patron'
    assert [device['model'] for device in local['devices'].values()] == ['00', '13']
    assert local['port'] == 50200


def test_argument_goes_before_the_environment(product, tmp_path, monkeypatch):
    monkeypatch.setenv('UNIPI_PRODUCT_ID', '0103')                     # S103, one board
    autogen.run(['-d', str(tmp_path), '-p', '0407'])
    assert len(written(tmp_path)['devices']) == 2


def test_product_id_by_the_environment(product, tmp_path, monkeypatch):
    monkeypatch.setenv('UNIPI_PRODUCT_ID', '0103')
    autogen.run(['-d', str(tmp_path)])
    local = written(tmp_path)
    assert (local['device_info']['family'], len(local['devices'])) == ('Neuron', 1)


def test_port_of_the_modbus_tcp_server(product, tmp_path):
    (tmp_path / 'unipitcp').write_text('LISTEN_PORT=502\n')
    autogen.run(['-d', str(tmp_path), '-p', '0407'])
    assert written(tmp_path)['port'] == 502


def test_without_product_id(product, tmp_path, capsys):
    with pytest.raises(SystemExit):
        autogen.run(['-d', str(tmp_path)])
    assert 'Device not recognized' in capsys.readouterr().out
    assert not (tmp_path / 'autogen.yaml').exists()
