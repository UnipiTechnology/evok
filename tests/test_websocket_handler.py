import pytest
from unittest.mock import MagicMock, patch


def test_on_close_removes_from_registered_devents():
    """on_close must remove self from registered_devents, not crash on registered_ws."""
    from evok.handlers_base import registered_devents
    from evok.handler_websocket import WebsocketHandler

    handler = WebsocketHandler.__new__(WebsocketHandler)
    registered_devents['all'] = {handler}

    # Patch stop_scanning to avoid needing real MODBUS_SLAVE devices
    with patch('evok.handler_websocket.Devices') as mock_devices:
        mock_devices.by_int.return_value = []
        handler.on_close()

    assert handler not in registered_devents.get('all', set())


def test_websocket_handler_imports_are_complete():
    """logging and traceback must be importable via the handler module."""
    import evok.handler_websocket as ws_mod
    assert hasattr(ws_mod, 'logging')
    assert hasattr(ws_mod, 'traceback')


def test_cmd_all_uses_correct_device_constants():
    """The 'all' command path must not reference undefined INPUT/RELAY names."""
    import ast, inspect, textwrap
    import evok.handler_websocket as ws_mod

    src = textwrap.dedent(inspect.getsource(ws_mod.WebsocketHandler.on_message))
    tree = ast.parse(src)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert 'INPUT' not in names, "INPUT is undefined — use DI"
    assert 'RELAY' not in names, "RELAY is undefined — use RO"
