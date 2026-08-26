"""Fake OWFS (owserver) — the 1-Wire counterpart to the Modbus mockbus.

Evok's ``OwBusDriver`` connects to an owserver daemon (default port 4304) via
the asyncowfs library and scans the 1-Wire bus for sensors. On real hardware
owserver talks to the kernel 1-Wire master; here we run a fake owserver that
serves a static device tree, so evok registers a fake DS18B20 without any
hardware or kernel driver.

The owserver wire protocol is implemented by ``asyncowfs.protocol.MessageProtocol``
(ships with asyncowfs, trio-free). We implement a minimal server loop that
handles the three commands evok issues — ``dirall`` (bus scan), ``read`` (sensor
value), and ``nop`` (keepalive) — against a nested-dict tree. This mirrors
``asyncowfs.mock.server.some_server`` but without its ``trio`` dependency (the
shipped mock imports trio for MultiError filtering in its test harness, which we
don't need).

The tree describes one DS18B20 at the same address the cassettes were recorded
against (``28.CD79A9080000.4A``), so the circuit (``28CD79A90800004A``) matches
and the harness's sensor tests resolve.

Usage:
    from tests.integration.mockbus.owserver import FakeOwServer
    srv = FakeOwServer(host="127.0.0.1", port=4304)
    await srv.start()    # serve forever (async)
    await srv.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
from functools import partial
from typing import Any

import anyio
from asyncowfs.error import IsDirError, NoEntryError, OWFSReplyError
from asyncowfs.protocol import MessageProtocol, OWMsg

# The DS18B20 the cassettes were recorded against. The dotted address is what
# owserver exposes; evok derives the circuit by stripping dots.
SENSOR_ADDRESS = "28.CD79A9080000.4A"

# A plausible room temperature. Evok rounds to 0.5°C (DS18B20.read_val_from_sens),
# so serve a value that rounds cleanly. The harness treats `value` as volatile
# in compare mode (10°C epsilon) and only asserts type/range in functional mode.
SENSOR_TEMP = "24.5"

# owserver exposes a /structure/<family> tree describing each device type's
# fields (name, type, size, access, ...). asyncowfs reads this on device setup
# to build accessors. This mirrors the structure a real owserver serves for a
# DS18B20 (family 28); only the fields evok reads (temperature, type, address)
# are strictly required, but the full set keeps asyncowfs happy.
_STRUCTURE_28 = {
    "address": "a,000000,000001,ro,000016,f,",
    "alias": "l,000000,000001,rw,000256,f,",
    "crc8": "a,000000,000001,ro,000002,f,",
    "family": "a,000000,000001,ro,000002,f,",
    "id": "a,000000,000001,ro,000012,f,",
    "latesttemp": "t,000000,000001,ro,000012,v,",
    "locator": "a,000000,000001,ro,000016,f,",
    "power": "y,000000,000001,ro,000001,v,",
    "temperature": "t,000000,000001,ro,000012,v,",
    "temphigh": "t,000000,000001,rw,000012,s,",
    "templow": "t,000000,000001,rw,000012,s,",
    "type": "a,000000,000001,ro,000032,f,",
}


def default_tree() -> dict:
    """The 1-Wire tree served by the fake owserver: one DS18B20.

    The ``bus.0`` subtree holds the sensor (``temperature`` is what evok reads
    via ``sens.get('temperature')``). The ``structure`` subtree describes the
    DS18B20's field layout to asyncowfs (family ``28``).
    """
    return {
        "bus.0": {
            SENSOR_ADDRESS: {
                "temperature": SENSOR_TEMP,
                "latesttemp": SENSOR_TEMP,
                "templow": "10",
                "temphigh": "40",
                "type": "DS18B20",
            }
        },
        "structure": {"28": _STRUCTURE_28},
    }


class _FakeMaster:
    """Minimal master object MessageProtocol expects (holds the stream)."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream


async def _serve_connection(tree: dict, socket: Any) -> None:
    """Handle one owserver client connection: read commands, reply from `tree`."""
    rdr = MessageProtocol(_FakeMaster(socket), is_server=True)
    try:
        async for command, format_flags, data, offset in rdr:
            try:
                if command == OWMsg.nop:
                    await rdr.write(0, format_flags, 0)
                elif command == OWMsg.dirall:
                    # Resolve the path in the tree; reply with a comma-separated
                    # list of "/<path>/<child>" entries.
                    data = data.rstrip(b"\0")
                    subtree: Any = tree
                    path: list[bytes] = []
                    for k in data.split(b"/"):
                        if k == b"":
                            continue
                        path.append(k)
                        try:
                            subtree = subtree[k.decode("utf-8")]
                        except KeyError:
                            raise NoEntryError(command, data) from None
                    res = [k.encode("utf-8") for k in sorted(subtree.keys())]
                    prefix = b"/" + b"/".join(path) + b"/" if path else b"/"
                    payload = b",".join(prefix + k for k in res)
                    await rdr.write(0, format_flags, len(payload), payload + b"\0")
                elif command == OWMsg.read:
                    # Walk the tree to the leaf; reply with its value as bytes.
                    data = data.rstrip(b"\0")
                    node: Any = tree
                    for k in data.split(b"/"):
                        if k == b"":
                            continue
                        try:
                            node = node[k.decode("utf-8")]
                        except KeyError:
                            raise NoEntryError(command, data) from None
                    if isinstance(node, dict):
                        raise IsDirError(command, data)
                    if not isinstance(node, bytes):
                        node = str(node).encode("utf-8")
                    await rdr.write(0, format_flags, len(node), node + b"\0")
                elif command == OWMsg.write:
                    # offset = length of the value tail; the rest is the path.
                    val = data[-offset:].decode("utf-8")
                    payload = data[:-offset].rstrip(b"\0")
                    node = tree
                    last: str | None = None
                    for k in payload.split(b"/"):
                        if k == b"":
                            continue
                        if last is not None:
                            node = node[last]
                        last = k.decode("utf-8")
                    if last is None or last not in node:
                        raise NoEntryError(command, data)
                    node[last] = val
                    await rdr.write(0, format_flags, 0)
                else:
                    raise RuntimeError(f"unknown owserver command {command}")
            except OWFSReplyError as err:
                await rdr.write(-err.err, format_flags)
    except (anyio.ClosedResourceError, anyio.BrokenResourceError, ConnectionError):
        pass
    finally:
        with contextlib.suppress(Exception):
            await socket.aclose()


class FakeOwServer:
    """A fake owserver serving a static 1-Wire device tree on a TCP port."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4304,
        tree: dict | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.tree = tree if tree is not None else default_tree()
        self._listener: Any = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start serving the fake owserver (non-blocking; call stop() to end)."""
        listener = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        self._listener = listener
        self._task = asyncio.create_task(listener.serve(partial(_serve_connection, self.tree)))
        # Give the listener a moment to bind.
        await asyncio.sleep(0.1)

    async def stop(self) -> None:
        if self._listener is not None:
            with contextlib.suppress(Exception):
                await self._listener.aclose()
            self._listener = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
