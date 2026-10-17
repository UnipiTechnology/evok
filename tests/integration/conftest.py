"""Pytest fixtures: base url, typed clients, parking of the outputs.

The harness is a black box: these fixtures never import the server. The clients
talk to a running Evok at ``EVOK_BASE_URL`` (default http://127.0.0.1:8080) and
validate every reply against the definition of the API (oracles.contract).

The server is either evok against the mockbus (no hardware)::

    uv run python mockbus/start.py
    EVOK_BASE_URL=http://127.0.0.1:8090 uv run pytest

or a device with the same inventory as the mockbus (Neuron M103, see fixtures/devices.yaml).
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

# Make the harness package importable when pytest is run from this dir.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # repo root, so `tests.integration.*` imports

from tests.integration.clients.http import HttpClient  # noqa: E402
from tests.integration.clients.rpc import RpcClient  # noqa: E402
from tests.integration.clients.webhook import WebhookReceiver  # noqa: E402
from tests.integration.clients.ws import WsSession  # noqa: E402

BASE_URL = os.environ.get("EVOK_BASE_URL", "http://127.0.0.1:8080")


@pytest.fixture(scope="session")
def evok_base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def device_inventory() -> dict:
    p = HERE / "fixtures" / "devices.yaml"
    return yaml.safe_load(p.read_text())


@pytest.fixture
def http(evok_base_url: str) -> HttpClient:
    return HttpClient(base_url=evok_base_url)


@pytest.fixture
def rpc(http: HttpClient) -> RpcClient:
    return RpcClient(http)


@pytest.fixture
def ws(evok_base_url: str) -> WsSession:
    return WsSession(base_url=evok_base_url)


@pytest.fixture
def webhook_receiver() -> WebhookReceiver:
    recv = WebhookReceiver().start()
    yield recv
    recv.stop()


@pytest.fixture
def park_output(http):
    """Park a single writable output in a known state before a read.

    Usage: ``next(park_output("do", "1_01", 0))`` sets DO 1_01 to 0, so the read
    `value` does not depend on the earlier write tests.
    """

    def _park(dev: str, circuit: str, value: int):
        http.post_form(f"/rest/{dev}/{circuit}/", {"value": str(value)})
        yield value
        http.post_form(f"/rest/{dev}/{circuit}/", {"value": str(value)})

    return _park


@pytest.fixture
def park_outputs(http):
    """Park the written outputs in a known state before and after an aggregate snapshot."""
    http.post_form("/rest/do/1_01/", {"value": "0"})
    http.post_form("/rest/ro/2_01/", {"value": "0"})
    yield
    http.post_form("/rest/do/1_01/", {"value": "0"})
    http.post_form("/rest/ro/2_01/", {"value": "0"})
