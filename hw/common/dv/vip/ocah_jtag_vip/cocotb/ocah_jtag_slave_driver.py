# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reactive IEEE 1149.1 TAP device model (the VIP's slave-side driver).

The slave side responds on TDO when the other end of the wire — a DUT JTAG
host port or the VIP's own master driver — drives TCK/TMS/TDI. It implements
the mandatory TAP data-register behavior from the public IEEE Std 1149.1
clause descriptions: IR capture presents 01 in the two LSBs, Test-Logic-Reset
selects the device-identification register (BYPASS when none is implemented),
unknown instructions select BYPASS, and BYPASS delays TDI to TDO by exactly
one TCK. User data registers come from an `OcahJtagDevice` map; writable
registers latch on Update-DR and each latch is recorded for test inspection.

`OcahJtagSlaveEngine` holds the pure per-edge logic with no simulator
handles, so it can be validated standalone (see
`examples/example_slave_selftest.py`); `OcahJtagSlaveDriver` pumps it from
the pins.

Rule provenance: implemented from the public IEEE Std 1149.1 clause
descriptions. No third-party device-model source was consulted or copied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import Edge, FallingEdge, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .ocah_jtag_device import OcahJtagDevice
from .ocah_jtag_state import OcahJtagState, next_jtag_state

__all__ = ["OcahJtagSlaveDriver", "OcahJtagSlaveEngine", "OcahJtagSlaveUpdate"]

# IEEE 1149.1 mandates the two IR LSBs capture 01.
IR_CAPTURE_LSBS = 0b01

_DEFAULT_SIGNAL_MAP: dict[str, str] = {
    "tck": "tck",
    "tms": "tms",
    "tdi": "tdi",
    "tdo": "tdo",
    "trst": "trst",
    "tdo_oen": "tdo_oen",
}


@dataclass(frozen=True)
class OcahJtagSlaveUpdate:
    """One Update-DR latch into a writable slave register."""

    reg_name: str
    opcode: int
    value: int
    width: int
    time_ns: float | None = None


class OcahJtagSlaveEngine:
    """Pure-logic reactive TAP device: one call per TCK edge.

    Timing contract (matches the master driver's cycle):
      * `clock_rise(tms, tdi)` — the rising edge: capture in Capture-x,
        shift in Shift-x (TDI enters the MSB), then the controller advances.
      * `clock_fall()` — the falling edge: latch in Update-x, re-select the
        reset instruction in Test-Logic-Reset, and return `(tdo, tdo_oen)`;
        TDO presents the selected shift register's LSB and TDO is enabled
        only while shifting.
    """

    def __init__(
        self,
        device: OcahJtagDevice,
        *,
        name: str = "OcahJtagSlaveEngine",
        ir_capture: int | None = None,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self.device = device
        self._ir_width = device.ir_width
        self._ir_mask = (1 << self._ir_width) - 1
        self._bypass_opcode = self._ir_mask
        capture = IR_CAPTURE_LSBS if ir_capture is None else int(ir_capture)
        self._ir_capture = (capture & self._ir_mask) | IR_CAPTURE_LSBS

        self._opcode_map = {reg.opcode: reg for reg in device.regs.values()}
        self._idcode_opcode: int | None = None
        if "IDCODE" in device.regs:
            self._idcode_opcode = device.regs["IDCODE"].opcode

        self.values: dict[str, int] = {reg.name: 0 for reg in device.regs.values()}
        self.updates: list[OcahJtagSlaveUpdate] = []

        self._state = OcahJtagState.TEST_LOGIC_RESET
        self._ir_shift = 0
        self._dr_shift = 0
        self._active_ir = 0
        self._select_reset_instruction()

    # ------------------------------------------------------------------
    # Test-facing register access (consumed via OcahJtagSlaveSequence).
    # ------------------------------------------------------------------

    def set_register(self, name: str, value: int) -> None:
        """Backdoor-set the value a register presents on Capture-DR."""
        reg = self.device.reg(name)
        self.values[name] = int(value) & ((1 << reg.width) - 1)

    def get_register(self, name: str) -> int:
        """Return a register's current stored value."""
        self.device.reg(name)
        return self.values[name]

    def clear_updates(self) -> None:
        self.updates.clear()

    @property
    def state(self) -> OcahJtagState:
        return self._state

    @property
    def active_instruction(self) -> int:
        return self._active_ir

    def reset(self) -> None:
        """Asynchronous TAP reset (TRST assertion)."""
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self._select_reset_instruction()

    # ------------------------------------------------------------------
    # Per-edge behavior.
    # ------------------------------------------------------------------

    def clock_rise(self, tms: int, tdi: int) -> None:
        state = self._state
        tdi = int(tdi) & 0x1
        if state == OcahJtagState.CAPTURE_IR:
            self._ir_shift = self._ir_capture
        elif state == OcahJtagState.SHIFT_IR:
            self._ir_shift = (self._ir_shift >> 1) | (tdi << (self._ir_width - 1))
        elif state == OcahJtagState.CAPTURE_DR:
            self._dr_shift = self._capture_dr_value()
        elif state == OcahJtagState.SHIFT_DR:
            width = self._selected_width()
            self._dr_shift = (self._dr_shift >> 1) | (tdi << (width - 1))
        self._state = next_jtag_state(state, tms)

    def clock_fall(self, *, time_ns: float | None = None) -> tuple[int, int]:
        state = self._state
        if state == OcahJtagState.UPDATE_IR:
            self._active_ir = self._ir_shift & self._ir_mask
        elif state == OcahJtagState.UPDATE_DR:
            self._latch_dr(time_ns)
        elif state == OcahJtagState.TEST_LOGIC_RESET:
            self._select_reset_instruction()

        if state == OcahJtagState.SHIFT_IR:
            return self._ir_shift & 0x1, 1
        if state == OcahJtagState.SHIFT_DR:
            return self._dr_shift & 0x1, 1
        return 0, 0

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    def _selected_reg(self):
        return self._opcode_map.get(self._active_ir)

    def _selected_width(self) -> int:
        reg = self._selected_reg()
        return reg.width if reg is not None and reg.width > 0 else 1

    def _capture_dr_value(self) -> int:
        reg = self._selected_reg()
        if reg is None or reg.name == "BYPASS":
            # BYPASS (and any unimplemented instruction) captures 0 into
            # the mandatory one-bit register.
            return 0
        if reg.name == "IDCODE":
            return self.device.idcode
        return self.values[reg.name]

    def _latch_dr(self, time_ns: float | None) -> None:
        reg = self._selected_reg()
        if reg is None or not reg.write:
            return
        value = self._dr_shift & ((1 << reg.width) - 1)
        self.values[reg.name] = value
        self.updates.append(
            OcahJtagSlaveUpdate(
                reg_name=reg.name,
                opcode=reg.opcode,
                value=value,
                width=reg.width,
                time_ns=time_ns,
            )
        )
        self.log.info("%s: Update-DR latched %s = 0x%x", self.name, reg.name, value)

    def _select_reset_instruction(self) -> None:
        if self._idcode_opcode is not None:
            self._active_ir = self._idcode_opcode
        else:
            self._active_ir = self._bypass_opcode


class _JtagIntfProxy:
    def __init__(self, intf, signal_map: dict[str, str]):
        object.__setattr__(self, "_intf", intf)
        object.__setattr__(self, "_map", signal_map)

    def __getattr__(self, name: str):
        smap = object.__getattribute__(self, "_map")
        intf = object.__getattribute__(self, "_intf")
        return getattr(intf, smap.get(name, name))


def _logic_int(signal, default: int = 0) -> int:
    try:
        return int(signal.value)
    except Exception:  # noqa: BLE001 - unresolved values treated as default.
        return default


def _time_ns() -> float:
    try:
        return float(get_sim_time(units="ns"))
    except TypeError:
        return float(get_sim_time(unit="ns"))


class OcahJtagSlaveDriver:
    """Pin-pumped reactive TAP device over one JTAG connection.

    Observes tck/tms/tdi/trst and drives tdo (and tdo_oen when present).
    All protocol behavior lives in the embedded `OcahJtagSlaveEngine`.
    """

    def __init__(
        self,
        jtag_intf,
        device: OcahJtagDevice,
        *,
        name: str = "OcahJtagSlaveDriver",
        signal_map: dict[str, str] | None = None,
        drive_tdo_oen: bool = True,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        smap = dict(_DEFAULT_SIGNAL_MAP)
        if signal_map:
            smap.update(signal_map)
        self._intf = _JtagIntfProxy(jtag_intf, smap)
        self._drive_tdo_oen = drive_tdo_oen and hasattr(self._intf, "tdo_oen")
        self.engine = OcahJtagSlaveEngine(device, name=f"{name}.engine")
        self._task = None
        self._trst_task = None
        self._running = False

    # Test-facing pass-throughs (surfaced via OcahJtagSlaveSequence).
    def set_register(self, name: str, value: int) -> None:
        self.engine.set_register(name, value)

    def get_register(self, name: str) -> int:
        return self.engine.get_register(name)

    def get_updates(self) -> list[OcahJtagSlaveUpdate]:
        return list(self.engine.updates)

    def clear_updates(self) -> None:
        self.engine.clear_updates()

    def device_state(self) -> OcahJtagState:
        """The device's current TAP controller state."""
        return self.engine.state

    def active_instruction(self) -> int:
        """The instruction currently selecting the device's data register."""
        return self.engine.active_instruction

    def get_statistics(self) -> dict[str, Any]:
        return {
            "state": self.engine.state.name,
            "active_instruction": self.engine.active_instruction,
            "updates": len(self.engine.updates),
        }

    def init_signals(self) -> None:
        """Drive the device-side outputs to their idle values."""
        self._intf.tdo.value = 0
        if self._drive_tdo_oen:
            self._intf.tdo_oen.value = 0

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.init_signals()
        self._task = cocotb.start_soon(self._run())
        if hasattr(self._intf, "trst"):
            self._trst_task = cocotb.start_soon(self._watch_trst())
        self.log.info("%s: responding on TDO", self.name)

    async def stop(self) -> None:
        self._running = False
        for task in (self._task, self._trst_task):
            if task is not None:
                task.kill()
        self._task = None
        self._trst_task = None

    async def _run(self) -> None:
        while self._running:
            await RisingEdge(self._intf.tck)
            await ReadOnly()
            tms = _logic_int(self._intf.tms)
            tdi = _logic_int(self._intf.tdi)
            in_reset = hasattr(self._intf, "trst") and _logic_int(self._intf.trst, 1) == 0
            if in_reset:
                self.engine.reset()
            else:
                self.engine.clock_rise(tms, tdi)
            await FallingEdge(self._intf.tck)
            tdo, oen = self.engine.clock_fall(time_ns=_time_ns())
            self._intf.tdo.value = tdo
            if self._drive_tdo_oen:
                self._intf.tdo_oen.value = oen

    async def _watch_trst(self) -> None:
        while self._running:
            await Edge(self._intf.trst)
            if _logic_int(self._intf.trst, 1) == 0:
                self.engine.reset()
                self.log.info("%s: TRST asserted -> Test-Logic-Reset", self.name)
