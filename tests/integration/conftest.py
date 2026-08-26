"""Pytest fixtures: mode, base url, cassette lifecycle, typed clients.

The harness is a black box: these fixtures never import the server. They provide
cassette-aware HTTP/RPC/WS clients and flush recorded cassettes at teardown.
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

# Make the harness package importable when pytest is run from this dir.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `tests.integration.*` imports

from tests.integration.cassette import BANK, mode  # noqa: E402
from tests.integration.clients.http import HttpClient  # noqa: E402
from tests.integration.clients.rpc import RpcClient  # noqa: E402
from tests.integration.clients.webhook import WebhookReceiver  # noqa: E402
from tests.integration.clients.ws import WsSession  # noqa: E402

BASE_URL = os.environ.get("EVOK_BASE_URL", "http://127.0.0.1:8080")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "record: capture live responses into golden cassettes")
    config.addinivalue_line("markers", "replay: serve assertions from cassettes (CI default)")
    config.addinivalue_line("markers", "live: run against a real running server")
    config.addinivalue_line("markers", "compare: run against a real server and diff vs cassettes")
    config.addinivalue_line("markers", "functional: mock-bus backed, no hardware")
    config.addinivalue_line("markers", "integration: requires real hardware / golden captures")


@pytest.fixture(scope="session")
def evok_base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def test_mode() -> str:
    return mode()


@pytest.fixture(scope="session")
def device_inventory() -> dict:
    p = HERE / "fixtures" / "devices.yaml"
    return yaml.safe_load(p.read_text())


@pytest.fixture
def cassette_name(request: pytest.FixtureRequest) -> str:
    """Each test owns a cassette named after the test node."""
    return request.node.nodeid.replace("/", "__")


@pytest.fixture
def http(evok_base_url: str, cassette_name: str) -> HttpClient:
    return HttpClient(base_url=evok_base_url, cassette_name=cassette_name)


@pytest.fixture
def rpc(http: HttpClient) -> RpcClient:
    return RpcClient(http)


@pytest.fixture
def ws(evok_base_url: str, cassette_name: str) -> WsSession:
    return WsSession(base_url=evok_base_url, cassette_name=cassette_name)


@pytest.fixture
def webhook_receiver() -> WebhookReceiver:
    recv = WebhookReceiver().start()
    yield recv
    recv.stop()


@pytest.fixture(autouse=True)
def _flush_cassettes_after_test() -> None:
    """Persist any recorded entries at end of each test (no-op in replay/live)."""
    yield
    BANK.flush()


@pytest.fixture
def park_output(http):
    """Park a single writable output in a known state before a read, in network modes.

    Usage: ``park_output("do", "1_01", 0)`` sets DO 1_01 to 0, yields, then
    restores to 0 on exit. Use for single-device READ tests of outputs so the
    read `value` is deterministic across record/compare runs (otherwise earlier
    write tests leave the device in varying states). Returns the value that
    was set (for assertions).
    """
    from tests.integration.cassette import ALLOW_NETWORK

    def _park(dev: str, circuit: str, value: int):
        if ALLOW_NETWORK:
            http.post_form(f"/rest/{dev}/{circuit}/", {"value": str(value)})
        yield value
        if ALLOW_NETWORK:
            http.post_form(f"/rest/{dev}/{circuit}/", {"value": str(value)})

    return _park


@pytest.fixture
def park_outputs(http):
    """Park writable outputs in a known state before aggregate-snapshot tests.

    Only runs in network modes (live/record/compare). Returns a context that,
    on exit, also restores DO 1_01 to 0. The WS `all` and `/rest/all` snapshots
    otherwise capture whatever state earlier write tests left behind, making
    `compare` mode report spurious `value` diffs on outputs (state drift, not a
    server regression).
    """
    from tests.integration.cassette import ALLOW_NETWORK

    if ALLOW_NETWORK:
        http.post_form("/rest/do/1_01/", {"value": "0"})
        http.post_form("/rest/ro/2_01/", {"value": "0"})
    yield
    if ALLOW_NETWORK:
        http.post_form("/rest/do/1_01/", {"value": "0"})
        http.post_form("/rest/ro/2_01/", {"value": "0"})


# Skip logic: integration tests need real hardware; functional tests need a mock
# bus. In replay mode everything runs from cassettes, so neither constraint
# applies — all tests are selected.

# Functional mode (EVOK_TEST_MODE=functional) is just `live` mode against a
# mockbus-backed evok instance. Process orchestration (starting mockbus + evok)
# is a separate operator concern — run `uv run python mockbus/start.py` in a
# terminal, then point the harness at it:
#   EVOK_TEST_MODE=functional EVOK_BASE_URL=http://127.0.0.1:8090 uv run pytest
# The harness stays a pure black-box client; no subprocess management here.


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    m = mode()
    for item in items:
        if m == "replay":
            # everything runnable from cassettes
            continue
        if m == "live" and item.get_closest_marker("integration"):
            # integration tests need hardware; only run when explicitly requested
            item.add_marker(
                pytest.mark.skip(
                    reason="integration test requires hardware; "
                    "set EVOK_TEST_MODE=integration to run"
                )
            )
