import logging

import pytest

from evok import devents


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    """ The registration replaces the module functions, they are restored after the test """
    monkeypatch.setattr(devents, 'status', devents.status)
    monkeypatch.setattr(devents, 'config', devents.config)


def failing(device, kwarg):
    raise RuntimeError('client failed')


@pytest.mark.parametrize('register, send, name', [
    (devents.register_status_cb, lambda: devents.status('device'), 'status'),
    (devents.register_config_cb, lambda: devents.config('device'), 'config'),
])
def test_error_of_callback_is_logged(register, send, name, caplog):
    """ The error of a callback was swallowed silently, the event is still not stopped by it """
    caplog.set_level(logging.ERROR, logger='evok')
    register(failing)
    send()
    assert f"Error in the {name} callback" in caplog.text and 'RuntimeError: client failed' in caplog.text


def test_callback_gets_device_and_arguments():
    received = []
    devents.register_status_cb(lambda device, kwarg: received.append((device, kwarg)))
    devents.status('device', value=1)
    assert received == [('device', {'value': 1})]
