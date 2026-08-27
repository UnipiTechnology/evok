"""Standalone launcher for the functional tier: mockbus + real evok.

Run this in a terminal to start a mockbus-backed evok instance, then point the
harness at it from another terminal:

    # terminal 1
    cd tests/integration
    uv run python mockbus/start.py

    # terminal 2
    EVOK_TEST_MODE=functional EVOK_BASE_URL=http://127.0.0.1:8090 uv run pytest

The mockbus (fake Modbus TCP server) listens on 127.0.0.1:5020; the real evok
server listens on 127.0.0.1:8090 and connects to the mockbus as its bus. Ctrl-C
stops both.

The harness stays a pure black-box client — it never launches processes. This
script is the only thing that manages the mockbus + evok lifecycle.
"""

import asyncio
import contextlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

# Make `tests.integration.mockbus.*` importable when run as a script.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tests.integration.mockbus.config import generate_config  # noqa: E402
from tests.integration.mockbus.server import MockBus  # noqa: E402

HERE = Path(__file__).resolve().parent
RUN_DIR = HERE / "run"
HW_DIR = HERE / "hw_definitions"

EVOCK_HTTP_PORT = 8090
MOCKBUS_PORT = 5020
OWSERVER_PORT = 4304
OWSERVER_SCRIPT = HERE / "run_owserver.py"


async def main() -> None:
    # 1. Prepare the run dir: config + hw_definitions.
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    target_hw = RUN_DIR / "hw_definitions"
    if target_hw.exists():
        shutil.rmtree(target_hw)
    shutil.copytree(HW_DIR, target_hw)
    generate_config(http_port=EVOCK_HTTP_PORT, modbus_port=MOCKBUS_PORT)
    print(f"[start] config written to {RUN_DIR / 'config.yaml'}")

    # 2. Start the mockbus (two-board M103: slave 1 = "00", slave 2 = "01").
    bus = MockBus(definitions={1: "00", 2: "01"}, host="127.0.0.1", port=MOCKBUS_PORT)
    await bus.start()
    print(f"[start] mockbus (fake Modbus TCP) listening on 127.0.0.1:{MOCKBUS_PORT}")

    # 3. Start the fake owserver (1-Wire DS18B20) on port 4304. Runs via the
    # main project's uv so asyncowfs (an evok dep) is available.
    import os

    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    ows = subprocess.Popen(  # noqa: ASYNC220
        ["uv", "run", "python", str(OWSERVER_SCRIPT), str(OWSERVER_PORT)],
        cwd=str(REPO_ROOT),
        env=env,
    )
    print(f"[start] fake owserver (1-Wire) listening on 127.0.0.1:{OWSERVER_PORT} (pid {ows.pid})")

    # 4. Launch the real evok server (foreground subprocess; inherits stdout/stderr).
    # Blocking subprocess in an async function is intentional — this is a
    # foreground launcher, not a concurrent coroutine. Runs via the main
    # project's uv so evok's own deps are available. Unset VIRTUAL_ENV so uv
    # targets the main project env, not the harness venv this script runs in.
    evok = subprocess.Popen(  # noqa: ASYNC220
        ["uv", "run", "evok", "-c", str(RUN_DIR)],
        cwd=str(REPO_ROOT),
        env=env,
    )
    print(f"[start] evok listening on 127.0.0.1:{EVOCK_HTTP_PORT} (pid {evok.pid})")
    print("[start] Ctrl-C to stop both.\n")

    def _stop(*_):
        print("\n[start] stopping...")
        evok.terminate()
        ows.terminate()
        try:
            evok.wait(timeout=10)
        except subprocess.TimeoutExpired:
            evok.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            ows.wait(timeout=5)
        asyncio.create_task(bus.stop())  # noqa: RUF006 -- fire-and-forget teardown

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Keep the loop alive until evok exits or we're signaled.
    while evok.poll() is None:  # noqa: ASYNC110 -- intentional poll loop for a foreground launcher
        await asyncio.sleep(0.5)
    await bus.stop()
    ows.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        ows.wait(timeout=5)
    print("[start] stopped.")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
