"""Record/replay/compare transport for the black-box harness.

The harness runs in four modes (selected by ``EVOK_TEST_MODE``):

* ``replay`` (default) — no server, no hardware. Every response/event is served
  from a previously recorded cassette in ``fixtures/golden/``.
* ``live`` — real requests hit a running server; responses are structurally
  asserted on by the test oracles.
* ``record`` — like ``live`` but persists every request/response pair into
  ``fixtures/golden/`` as the new regression oracle.
* ``compare`` — like ``live``, but after each request the fresh response is
  DIFFED against the recorded cassette entry. This is the true regression-
  comparison mode: "validate a running instance against the recording".

A cassette is a single JSON file keyed by a canonical request id::

    {
      "<reqid>": {
        "request":  {"kind": "http", "method": "GET", "path": "/rest/di/1_01"},
        "response": {"status": 200, "body": "{...json...}"}
      },
      ...
    }

For WebSocket, entries carry ``"kind": "ws"`` and a ``"stream"`` of messages
ordered by receipt. The reqid is deterministic so a replay of the same test
hits the same cassette entry regardless of run order.

This module is intentionally server-agnostic: it never imports or references the
server under test. It only reads/writes golden files and gates network calls.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"

MODE = os.environ.get("EVOK_TEST_MODE", "replay").lower()
# When True, network calls are made (live / record / compare). When False, only cassettes.
ALLOW_NETWORK = MODE in ("live", "record", "compare", "functional")
# When True, observed responses are persisted to GOLDEN_DIR (record only).
PERSIST = MODE == "record"
# When True, fresh responses are diffed against the cassette (compare only).
DIFF_AGAINST_CASSETTE = MODE == "compare"

# Default absolute tolerance for float comparisons. Most Evok floats are
# physical readings (V, C, mA) or derived scalars; 1e-3 is below the firmware's
# own rounding (e.g. AO step 0.0025V, AI rounded to 3 decimals, temp to 0.5C).
# Used only for fields NOT classified below.
DEFAULT_EPS = 1e-3

# Looser tolerance for bare numeric elements in RPC result lists (positional
# readings/clocks with no dict keys), e.g. sensor_get -> [value, lost, readtime,
# interval]. These drift with environment/time; 1.0 covers temperature (°C)
# and analog noise while still catching gross regressions (wrong type, order,
# missing element).
_BARE_LIST_EPS = 1.0

# Fields whose values are inherently time/run-dependent and must be ignored
# (not even epsilon-compared) when diffing. These are monotonic clocks,
# communication stats, or per-call identifiers that change every request.
VOLATILE_FIELDS: frozenset[str] = frozenset(
    {
        "time",  # sensor readtime (anyio clock)
        "last_comm",  # modbus_slave time since last scan
        "readtime",  # alternate sensor clock key
        "id",  # JSON-RPC request id echoed in the response body
    }
)

# The `value` field is volatile for EVERY device type in compare mode.
# Rationale: Evok's device model is scan-cache based. `set()` returns `full()`
# whose `value` reflects the LAST scan, not the just-written value, so write
# responses and aggregate snapshots capture non-deterministic, timing-dependent
# state. Even fresh single-device reads of inputs (ai/sensor) are environmental
# noise. The only place `value` is a stable contract is a read immediately after
# a park (asserted by the oracles, not by compare). Therefore compare mode gates
# structure + all non-`value` fields exactly, and treats `value` as volatile.
# This is the correct regression gate for this architecture: it catches dropped/
# added fields, type changes, mode/modes/range/unit drift, status changes, and
# error-envelope regressions, without false positives from scan-cache timing.
INPUT_DEVTYPES_VALUE_IS_VOLATILE: frozenset[str] = frozenset(
    {
        "ai",
        "di",
        # outputs: scan-cache-lagged in write responses & aggregate snapshots
        "ro",
        "do",
        "led",
        "ao",
        "wd",
        "owpower",
        "register",
    }
)
# Sensor (1-Wire) `value` is temperature — an environmental reading that drifts
# (observed ~2°C between record/compare runs). Ignore it entirely is too lax (a
# frozen/broken sensor returning 0°C or an error code like -127 would pass);
# epsilon-compare it instead. 10°C tolerates real drift while catching a
# sensor that has died, disconnected, or gone full-scale bogus.
SENSOR_DEVTYPES: frozenset[str] = frozenset({"sensor", "temp", "1wdevice"})
SENSOR_VALUE_EPS: float = 10.0
OUTPUT_DEVTYPES: frozenset[str] = frozenset(
    {
        "ro",
        "do",
        "led",
        "ao",
        "wd",
        "owpower",
        "register",
    }
)

# Fields that are floats and need epsilon comparison rather than exact equality.
# Applied only when the value is NOT volatile (i.e. on outputs). Anything not in
# here and not in VOLATILE_FIELDS is compared exactly (or, for lists/dicts,
# recursively).
FLOAT_EPS_FIELDS: frozenset[str] = frozenset(
    {
        "value",  # analog output value (commanded, but float-quantized)
        "pwm_freq",  # derived PWM frequency
        "pwm_duty",  # PWM duty
        "scan_interval",  # 1/scan_freq, often non-integer
        "interval",  # sensor/owbus polling interval (may be float)
    }
)


def _value_is_volatile_for(dev: str | None) -> bool:
    """True if the `value` field should be ignored for this devtype.

    Returns True for all known device types (see INPUT_DEVTYPES_VALUE_IS_VOLATILE,
    which now includes outputs due to scan-cache lag) AND for ``None`` (a
    property-read response like ``{"value": 0.008}`` has no ``dev`` field but
    `value` is still an analog reading -> volatile).
    """
    return dev is None or dev in INPUT_DEVTYPES_VALUE_IS_VOLATILE


def _numeric_abs_diff(a: Any, b: Any) -> float:
    """Absolute difference between two numeric values (0 if either is non-numeric)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return 0.0 if a is b else float("inf")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b))
    return float("inf")  # type mismatch -> treat as infinitely different


def _dev_of(entry: Any) -> str | None:
    """Best-effort extract the `dev` field from a payload entry (dict or list-of-dicts)."""
    if isinstance(entry, dict):
        return entry.get("dev")
    return None


def _canon(value: Any) -> Any:
    """Normalize a JSON-ish value for deterministic comparison/keying."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def request_id(kind: str, **parts: Any) -> str:
    """Stable id for a request so replay hits the right cassette entry."""
    blob = json.dumps({"kind": kind, **_canon(parts)}, sort_keys=True, default=str)
    import hashlib

    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Diff engine for compare mode.
# --------------------------------------------------------------------------- #


class Diff:
    """A single difference found between a recorded and a live value."""

    def __init__(self, path: str, recorded: Any, live: Any, reason: str) -> None:
        self.path = path
        self.recorded = recorded
        self.live = live
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.path}: {self.reason} (recorded={self.recorded!r}, live={self.live!r})"


def diff_values(
    recorded: Any,
    live: Any,
    path: str = "",
    dev: str | None = None,
    in_list: bool = False,
) -> list[Diff]:
    """Structurally diff a recorded value against a live value.

    Rules:
      * dicts  -> recurse over the union of keys; ignore VOLATILE_FIELDS;
        epsilon-compare FLOAT_EPS_FIELDS; exact for the rest. The `dev` field
        inside a dict seeds the per-devtype `value` volatility policy.
      * lists  -> must be same length; recurse element-wise with in_list=True
        so output `value` (state, not contract) is treated as volatile inside
        aggregate snapshots.
      * floats -> epsilon compare (DEFAULT_EPS).
      * ints/strs/bools/None -> exact equality.
    """
    diffs: list[Diff] = []

    if isinstance(recorded, dict) and isinstance(live, dict):
        cur_dev = recorded.get("dev") or live.get("dev") or dev
        keys = set(recorded) | set(live)
        for k in sorted(keys):
            sub = f"{path}.{k}" if path else k
            if k in VOLATILE_FIELDS:
                continue
            if k == "value" and _value_is_volatile_for(cur_dev):
                continue
            # Sensor temperature: epsilon-compare (not ignored) so a frozen/broken
            # sensor is caught while tolerating environmental drift. BUT skip the
            # comparison entirely if either side reports `lost: true` — a
            # disconnected sensor's `value` is non-contract (POR 85C, stale
            # last-reading, or None) regardless of which side recorded it, so a
            # transient disconnect on either side must not cause a false failure.
            if k == "value" and cur_dev in SENSOR_DEVTYPES:
                if recorded.get("lost") is True or live.get("lost") is True:
                    continue
                if _numeric_abs_diff(recorded[k], live[k]) > SENSOR_VALUE_EPS:
                    diffs.append(
                        Diff(
                            sub,
                            recorded[k],
                            live[k],
                            f"sensor value diff > eps ({SENSOR_VALUE_EPS})",
                        )
                    )
                continue
            # RPC `result` that is a bare float is a reading (e.g.
            # sensor_get_value -> temperature). Epsilon-compare it with the
            # sensor eps so drift is tolerated but a frozen/broken sensor fails.
            # Bare-int results (relay_get/output_set -> 0/1) stay exact.
            if k == "result" and isinstance(recorded[k], float) and isinstance(live[k], float):
                if _numeric_abs_diff(recorded[k], live[k]) > SENSOR_VALUE_EPS:
                    diffs.append(
                        Diff(sub, recorded[k], live[k], f"reading diff > eps ({SENSOR_VALUE_EPS})")
                    )
                continue
            if k == "value" and in_list and cur_dev in OUTPUT_DEVTYPES:
                continue
            if k not in recorded:
                diffs.append(Diff(sub, None, live[k], "key only in live"))
                continue
            if k not in live:
                diffs.append(Diff(sub, recorded[k], None, "key only in recorded"))
                continue
            diffs.extend(diff_values(recorded[k], live[k], sub, cur_dev, in_list))
        return diffs

    if isinstance(recorded, list) and isinstance(live, list):
        if len(recorded) != len(live):
            diffs.append(Diff(path, recorded, live, f"list length {len(recorded)} != {len(live)}"))
            return diffs
        # Bare RPC result lists (e.g. sensor_get -> [value, lost, readtime, interval])
        # carry readings/clocks at positional indices with no dict keys to key
        # the volatility policy off. Treat bare numeric elements here as
        # epsilon-tolerant with a looser bound: these are physical readings or
        # monotonic clocks, never identity-relevant contract values.
        for i, (r, lv) in enumerate(zip(recorded, live, strict=False)):
            # If an element is a dict, recurse normally (it carries its own `dev`).
            if isinstance(r, dict) or isinstance(lv, dict):
                diffs.extend(diff_values(r, lv, f"{path}[{i}]", dev, in_list=True))
                continue
            # Bare numeric element: positional RPC results are readings/clocks
            # (sensor_get -> [value, lost, readtime, interval]). None are stable
            # contracts (environmental noise + monotonic clocks); the oracles
            # assert their types/arity, compare skips their exact values.
            if (
                isinstance(r, (int, float))
                and isinstance(lv, (int, float))
                and not isinstance(r, bool)
                and not isinstance(lv, bool)
            ):
                continue
            # Otherwise exact.
            diffs.extend(diff_values(r, lv, f"{path}[{i}]", dev, in_list=True))
        return diffs

    # Epsilon for floats (and numeric type crossings like 0 vs 0.0).
    if (
        isinstance(recorded, (int, float))
        and isinstance(live, (int, float))
        and not isinstance(recorded, bool)
        and not isinstance(live, bool)
    ):
        if abs(float(recorded) - float(live)) > DEFAULT_EPS:
            diffs.append(Diff(path, recorded, live, f"numeric diff > eps ({DEFAULT_EPS})"))
        return diffs

    if isinstance(recorded, bool) or isinstance(live, bool):
        if recorded is not live:
            diffs.append(Diff(path, recorded, live, "bool diff"))
        return diffs

    if recorded != live:
        diffs.append(Diff(path, recorded, live, "value diff"))

    return diffs


@dataclass
class Cassette:
    """In-memory view of one golden cassette file."""

    name: str
    entries: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, name: str) -> Self:
        path = GOLDEN_DIR / f"{name}.json"
        if path.exists():  # noqa: SIM108 -- clearer than a ternary for the load fallback
            entries = json.loads(path.read_text())
        else:
            entries = {}
        return cls(name=name, entries=entries)

    def get(self, reqid: str) -> dict | None:
        return self.entries.get(reqid)

    def put(self, reqid: str, entry: dict) -> None:
        self.entries[reqid] = entry

    def flush(self) -> None:
        if not PERSIST:
            return
        if not self.entries:
            return
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path = GOLDEN_DIR / f"{self.name}.json"
        path.write_text(json.dumps(self.entries, indent=2, sort_keys=True))


class CassetteBank:
    """Per-test cassette cache; flushed at teardown."""

    def __init__(self) -> None:
        self._caches: dict[str, Cassette] = {}

    def cassette(self, name: str) -> Cassette:
        if name not in self._caches:
            self._caches[name] = Cassette.load(name)
        return self._caches[name]

    def flush(self) -> None:
        for c in self._caches.values():
            c.flush()


BANK = CassetteBank()


def mode() -> str:
    return MODE
