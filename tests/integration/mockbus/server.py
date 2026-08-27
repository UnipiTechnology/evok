"""Fake Modbus TCP server — the mockbus.

A stand-in PLC on the bus side. The real Evok server connects to this instead of
real hardware, so the harness can exercise the full server stack (routing,
validation, dispatch, serialization) in CI without a device.

It is driven by hw_definition YAML files (the SAME files the real Evok uses,
copied from the device's ``/etc/evok/hw_definitions/``): it reads the
``modbus_register_blocks`` to know which register ranges to serve, and
initializes them to zero (sane defaults — evok registers devices from the
definition's ``modbus_features`` regardless of values; values only affect
``full()`` output, which the harness treats as volatile in compare mode).

A single mockbus instance can serve **multiple slave-ids** on one TCP port, each
backed by its own definition. The M103 uses two sections: slave-id 1 (model
``00`` — the CPU board: DI/DO/AI/AO/LED/WD/owpower) and slave-id 2 (model ``01``
— the relay board: DI/RO/WD). Coils are served too (val_coil for RO/DO/LED/
NV_SAVE/OWPOWER). Writes update the register/coil store so reads reflect them —
a minimal but faithful round-trip for the device model.

This is NOT a mock of the Evok server — it is a fake PLC. The server under test
is the real Evok, connecting to this fake bus exactly as it would to real hardware.

Usage:
    from tests.integration.mockbus import MockBus
    bus = MockBus(definitions={1: "00", 2: "01"}, host="127.0.0.1", port=5020)
    await bus.start()    # serve forever (async)
    await bus.stop()

See mockbus/README.md for the functional-tier architecture.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

import yaml
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartAsyncTcpServer

HW_DIR = Path(__file__).resolve().parent / "hw_definitions"

# Function codes for coil writes (mirror these into holding registers).
_COIL_WRITE_FCS = {0x05, 0x0F}


class _MirroringSlaveContext(ModbusSlaveContext):
    """A slave context that mirrors coil writes into holding-register bits.

    Evok reads output state from a holding register (val_reg, bitmask) on scan,
    but writes outputs via coils (val_coil). On real hardware writing a coil
    changes the physical output, which the next scan reads back from the
    register. A naïve mock keeps the two stores separate, so evok's scan-cache
    diff never sees a transition and no WS/REST change event fires. This class
    closes that gap: on a coil write, it also updates the mapped bit in the
    holding register, so the round-trip mirrors the real device.
    """

    def __init__(self, coil_to_reg, hr_block, di_block, co_block) -> None:
        super().__init__(hr=hr_block, di=di_block, co=co_block, zero_mode=True)
        # {coil_address: (reg_address, bit_index)} built from the hw definition.
        self._coil_to_reg = coil_to_reg

    def setValues(self, fc_as_hex, address, values):
        super().setValues(fc_as_hex, address, values)
        if fc_as_hex not in _COIL_WRITE_FCS:
            return
        for i, v in enumerate(values):
            coil = address + i
            mapping = self._coil_to_reg.get(coil)
            if mapping is None:
                continue
            reg, bit = mapping
            cur = self.getValues(0x03, reg, 1)[0]
            cur = (cur | (1 << bit)) if v else (cur & ~(1 << bit))
            self.setValues(0x06, reg, [cur])


def _coil_to_reg_map(hw: dict) -> dict[int, tuple[int, int]]:
    """Build {coil_addr: (reg_addr, bit)} for every feature with val_coil + val_reg.

    Only DO/RO/LED have both (a coil to write and a bitmask register to read);
    DI is read-only, WD/OWPOWER/NV_SAVE are coil-only. The register is a single
    bitmask word; bit i corresponds to device i within the feature.
    """
    mapping: dict[int, tuple[int, int]] = {}
    for feat in hw.get("modbus_features", []):
        if "val_coil" in feat and "val_reg" in feat and feat["type"] in {"DO", "RO", "LED"}:
            base_coil = feat["val_coil"]
            reg = feat["val_reg"]
            for i in range(feat.get("count", 1)):
                mapping[base_coil + i] = (reg, i)
    return mapping


class MockBus:
    """A fake Modbus TCP server initialized from one or more hw_definition YAMLs.

    Each entry in ``definitions`` maps a Modbus slave-id to an hw_definition file
    name (without ``.yaml``). All slaves are served on a single TCP port.
    """

    def __init__(
        self,
        definitions: dict[int, str] | None = None,
        *,
        host: str = "127.0.0.1",
        port: int = 5020,
    ) -> None:
        # Default: the two-board Neuron M103 (slave 1 = CPU board "00",
        # slave 2 = relay board "01").
        self.definitions = definitions or {1: "00", 2: "01"}
        self.host = host
        self.port = port
        self._server: Any = None
        self._task: asyncio.Task | None = None
        self._context: ModbusServerContext | None = None
        self._hws: dict[int, dict] = {}  # slave-id -> parsed hw definition
        self._load_definitions()

    def _load_definitions(self) -> None:
        for slave_id, name in self.definitions.items():
            path = HW_DIR / f"{name}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"hw_definition {name!r} not found in {HW_DIR}")
            self._hws[slave_id] = yaml.safe_load(path.read_text())

    def _init_store(self) -> ModbusServerContext:
        """Build a pymodbus datastore with one mirroring slave context per slave-id.

        Each slave's holding-register and coil blocks are sized to cover every
        register/coil address its definition references, and zero-initialized.
        """
        slaves: dict[int, ModbusSlaveContext] = {}
        for slave_id, hw in self._hws.items():
            blocks = hw.get("modbus_register_blocks", [])
            features = hw.get("modbus_features", [])
            max_reg = 0
            for blk in blocks:
                max_reg = max(max_reg, blk["start_reg"] + blk["count"])
            max_coil = 0
            for feat in features:
                if "val_coil" in feat:
                    max_coil = max(max_coil, feat["val_coil"] + feat.get("count", 1))
            hr_block = ModbusSequentialDataBlock(0, [0] * (max_reg + 1))
            di_block = ModbusSequentialDataBlock(0, [0] * 16)
            co_block = ModbusSequentialDataBlock(0, [False] * (max_coil + 1))
            slaves[slave_id] = _MirroringSlaveContext(
                _coil_to_reg_map(hw), hr_block, di_block, co_block
            )
        ctx = ModbusServerContext(slaves=slaves, single=False)
        self._context = ctx
        return ctx

    async def start(self) -> None:
        """Start the fake Modbus TCP server (non-blocking; call stop() to end)."""
        ctx = self._init_store()
        # StartAsyncTcpServer blocks; run it in a task so we can stop later.
        self._task = asyncio.create_task(
            StartAsyncTcpServer(context=ctx, address=(self.host, self.port))
        )
        # Give the server a moment to bind.
        await asyncio.sleep(0.2)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    # --- inspection / test helpers (read the in-memory store) ---

    def _slave(self, slave_id: int) -> ModbusSlaveContext:
        if self._context is None:
            raise RuntimeError("MockBus not started")
        return self._context[slave_id]

    def get_register(self, slave_id: int, addr: int) -> int:
        return self._slave(slave_id).getValues(0x03, addr, count=1)[0]

    def set_register(self, slave_id: int, addr: int, value: int) -> None:
        self._slave(slave_id).setValues(0x06, addr, [value & 0xFFFF])

    def get_coil(self, slave_id: int, addr: int) -> bool:
        return bool(self._slave(slave_id).getValues(0x01, addr, count=1)[0])

    def set_coil(self, slave_id: int, addr: int, value: bool) -> None:
        self._slave(slave_id).setValues(0x05, addr, [bool(value)])
