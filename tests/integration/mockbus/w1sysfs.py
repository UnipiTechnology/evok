"""Fake 1-Wire sysfs tree — the counterpart to the Modbus mockbus.

Evok reads the 1-Wire sensors from the 1-Wire subsystem of the kernel,
``/sys/bus/w1/devices`` (see ``evok/w1/sysfs.py``); owserver is not used any
more. On real hardware the kernel searches the bus and the slave drivers expose
the values under that path. Here we present the same layout as plain files, so
evok registers a fake DS18B20 without any hardware or kernel driver.

The path is fixed (``/sys/bus/w1/devices``), so the tree cannot simply be placed
somewhere and pointed at. Instead the launcher runs inside a private **mount
namespace** (``unshare -rm``, no root needed) where a tmpfs is mounted over
``/sys/bus`` and the fake tree is copied into ``/sys/bus/w1/devices``. The real
evok process is a child of the launcher, so it inherits the namespace and sees
the fake bus.

Usage (inside the namespace, as done by ``start.py``)::

    tree = create_tree(RUN_DIR / "fake_w1")
    mount_over_sysfs(tree)          # /sys/bus/w1/devices is now the fake tree

Before that, ``ensure_mount_namespace()`` re-execs the calling script under
``unshare -rm`` if it is not already namespaced.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from pathlib import Path

# Names of the fake master and the DS18B20 the golden cassettes were recorded
# against. The sysfs name carries the serial number in reverse byte order of the
# owfs address; derive it from the address so the two never drift apart.
SENSOR_ADDRESS = "28.CD79A9080000.4A"
SENSOR_CIRCUIT = "28CD79A90800004A"
MASTER_NAME = "w1_bus_master1"

# millidegrees Celsius, the format a w1_therm slave exposes (24500 -> 24.5 C)
SENSOR_TEMPERATURE_MC = "24500"

SYS_BUS = "/sys/bus"
SYS_W1_DEVICES = "/sys/bus/w1/devices"

# The environment flag marking a process already re-executed into the namespace.
_NS_FLAG = "EVOK_MOCKBUS_NS"


def sysfs_name(address: str) -> str:
    """The sysfs name of an owfs address, e.g. 28.CD79A9080000.4A -> 28-000008a979cd

    The serial number is kept in reverse byte order, which is what the kernel
    uses for the device name.
    """
    key = address.replace(".", "").upper()[:14]
    family, serial = key[:2], key[2:]
    return f"{family}-{bytes.fromhex(serial)[::-1].hex()}"


SENSOR_SYSFS_NAME = sysfs_name(SENSOR_ADDRESS)


def create_tree(root: Path) -> Path:
    """Write the fake 1-Wire tree under `root` and return `root`.

    The master lists its slaves in ``w1_master_slaves``. ``w1_master_search``
    and ``therm_bulk_read`` are writable, so evok's ``do_scan`` (forced
    search) and bulk thermometer conversion are exercised instead of falling
    back to the "no write access" paths.
    """
    master = root / MASTER_NAME
    master.mkdir(parents=True, exist_ok=True)
    (master / "w1_master_slaves").write_text(SENSOR_SYSFS_NAME + "\n")
    (master / "w1_master_search").write_text("0\n")
    (master / "therm_bulk_read").write_text("0\n")
    sensor = root / SENSOR_SYSFS_NAME
    sensor.mkdir(exist_ok=True)
    (sensor / "temperature").write_text(SENSOR_TEMPERATURE_MC + "\n")
    return root


def _mount_tmpfs(target: str) -> None:
    """Mount a fresh tmpfs on `target` (needs a mount namespace)."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mount.restype = ctypes.c_int
    libc.mount.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    result = libc.mount(b"tmpfs", target.encode(), b"tmpfs", 0, None)
    if result != 0:
        errno = ctypes.get_errno()
        raise OSError(
            errno,
            f"cannot mount tmpfs on {target}: {os.strerror(errno)} (is a "
            f"mount namespace active, e.g. 'unshare -rm'?)",
        )


def mount_over_sysfs(tree: Path) -> None:
    """Make `tree` the content of /sys/bus/w1/devices inside the mount namespace."""
    _mount_tmpfs(SYS_BUS)
    devices = Path(SYS_W1_DEVICES)
    devices.mkdir(parents=True, exist_ok=True)
    for item in tree.iterdir():
        dest = devices / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)


def in_mount_namespace() -> bool:
    """True if this process already runs in its own mount namespace."""
    if os.environ.get(_NS_FLAG) == "1":
        return True
    try:
        return os.stat("/proc/self/ns/mnt").st_ino != os.stat("/proc/1/ns/mnt").st_ino
    except OSError:
        return False


def ensure_mount_namespace() -> None:
    """Re-exec the current process under ``unshare -rm`` if needed.

    A private mount namespace created by ``unshare -r`` needs no root: the
    current user is mapped to root inside it. `-r` does not touch the network
    namespace, so the loopback TCP ports stay shared with the harness.
    """
    if in_mount_namespace():
        return
    os.environ[_NS_FLAG] = "1"
    try:
        os.execvp("unshare", ["unshare", "-rm", "--", sys.executable, *sys.argv])
    except FileNotFoundError as err:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "the functional tier needs 'unshare' (util-linux) to fake "
            "/sys/bus/w1/devices in a private mount namespace"
        ) from err
