"""Standalone runner for the fake owserver.

Launched by ``start.py`` as a subprocess via the main project's ``uv run`` (so
``asyncowfs`` is available — it's an evok dependency, not a harness one). Keeps
the harness venv free of evok internals.

    uv run python tests/integration/mockbus/run_owserver.py [port]

Runs in the foreground; Ctrl-C / SIGTERM stops it.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

# Make `owserver` importable when run as a script (it only needs asyncowfs,
# which is in the main project venv). We add this file's own directory so the
# relative import `from owserver import FakeOwServer` resolves.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from owserver import FakeOwServer  # noqa: E402


async def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4304
    srv = FakeOwServer(host="127.0.0.1", port=port)
    await srv.start()
    print(f"[owserver] fake owserver (1-Wire) listening on 127.0.0.1:{port}")
    # Serve forever until interrupted.
    try:
        await asyncio.Event().wait()
    finally:
        await srv.stop()
        print("[owserver] stopped.")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
