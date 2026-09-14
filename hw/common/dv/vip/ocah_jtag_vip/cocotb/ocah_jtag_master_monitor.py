# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive OCAH IEEE 1149.1 TAP monitor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from cocotbext.jtag import JTAGBus

from .ocah_jtag_item import OcahJtagScanItem
from .ocah_jtag_state import OcahJtagState, next_jtag_state

__all__ = ["OcahJtagMasterMonitor"]

_MAX_HISTORY_DEFAULT = 2000
_DEFAULT_SIGNAL_MAP: dict[str, str] = {
    "tck": "tck",
    "tms": "tms",
    "tdi": "tdi",
    "tdo": "tdo",
    "trst": "trst",
    "tdo_oen": "tdo_oen",
}


class _JtagIntfProxy:
    def __init__(self, intf, signal_map: dict[str, str]):
        object.__setattr__(self, "_intf", intf)
        object.__setattr__(self, "_map", signal_map)
        object.__setattr__(self, "_log", logging.getLogger("OcahJtagMasterMonitor._intf"))

    def __getattr__(self, name: str):
        if name == "_log":
            return object.__getattribute__(self, "_log")
        smap = object.__getattribute__(self, "_map")
        intf = object.__getattribute__(self, "_intf")
        return getattr(intf, smap.get(name, name))

    def __dir__(self):
        intf = object.__getattribute__(self, "_intf")
        smap = object.__getattribute__(self, "_map")
        return sorted(set(dir(intf)) | set(smap))


def _logic_int(signal, default: int = 0) -> int:
    try:
        return int(signal.value)
    except Exception:  # noqa: BLE001
        return default


def _time_ns() -> float:
    try:
        return float(get_sim_time(units="ns"))
    except TypeError:
        return float(get_sim_time(unit="ns"))


class OcahJtagMasterMonitor:
    """Passive TAP monitor that emits `OcahJtagScanItem` records."""

    def __init__(
        self,
        jtag_intf,
        *,
        name: str = "OcahJtagMasterMonitor",
        max_history: int = _MAX_HISTORY_DEFAULT,
        signal_map: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self._max_history = int(max_history)

        smap = dict(_DEFAULT_SIGNAL_MAP)
        if signal_map:
            smap.update(signal_map)

        if isinstance(jtag_intf, JTAGBus):
            self.bus = jtag_intf
        else:
            self.bus = JTAGBus.from_entity(_JtagIntfProxy(jtag_intf, smap))

        self._callbacks: list[Callable[[OcahJtagScanItem], None]] = []
        self.callback_errors = 0
        self._ir_callbacks: list[Callable[[OcahJtagScanItem], None]] = []
        self._dr_callbacks: list[Callable[[OcahJtagScanItem], None]] = []
        self._ir_history: list[OcahJtagScanItem] = []
        self._dr_history: list[OcahJtagScanItem] = []
        self._task = None
        self._running = False
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self._active_instruction: int | None = None
        self._state_changes = 0
        self._total_clocks = 0
        self._resets = 0

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        *,
        name: str = "OcahJtagMasterMonitor",
        max_history: int = _MAX_HISTORY_DEFAULT,
    ) -> "OcahJtagMasterMonitor":
        """Construct from flattened JTAG signals."""
        return cls(JTAGBus.from_prefix(dut, prefix), name=name, max_history=max_history)

    def add_item_callback(self, fn: Callable[[OcahJtagScanItem], None]) -> None:
        self._callbacks.append(fn)

    def add_ir_callback(self, fn: Callable[[OcahJtagScanItem], None]) -> None:
        self._ir_callbacks.append(fn)

    def add_dr_callback(self, fn: Callable[[OcahJtagScanItem], None]) -> None:
        self._dr_callbacks.append(fn)

    async def start(self) -> None:
        """Start passive monitoring."""
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._run())
        self.log.info("%s: monitoring started", self.name)

    async def stop(self) -> None:
        """Stop passive monitoring."""
        self._running = False
        if self._task is not None:
            self._task.kill()
            self._task = None
        self.log.info("%s: monitoring stopped", self.name)

    def get_ir_transactions(self) -> list[OcahJtagScanItem]:
        return list(self._ir_history)

    def get_dr_transactions(self) -> list[OcahJtagScanItem]:
        return list(self._dr_history)

    def get_items(self) -> list[OcahJtagScanItem]:
        return [*self._ir_history, *self._dr_history]

    def clear_history(self) -> None:
        self._ir_history.clear()
        self._dr_history.clear()

    def get_statistics(self) -> dict[str, Any]:
        return {
            "total_clocks": self._total_clocks,
            "ir_transactions": len(self._ir_history),
            "dr_transactions": len(self._dr_history),
            "state_changes": self._state_changes,
            "resets": self._resets,
            "current_state": self._state.name,
            "current_instruction": self._active_instruction,
            "callback_errors": self.callback_errors,
        }

    async def _run(self) -> None:
        tdi_value = 0
        tdo_value = 0
        bit_count = 0
        start_time = None
        start_state = None
        pending_ir: int | None = None

        while self._running:
            await RisingEdge(self.bus.tck)
            await ReadOnly()
            self._total_clocks += 1

            tms = _logic_int(self.bus.tms)
            tdi = _logic_int(self.bus.tdi)
            tdo = _logic_int(self.bus.tdo)
            previous = self._state

            if hasattr(self.bus, "trst") and _logic_int(self.bus.trst, 1) == 0:
                self._state = OcahJtagState.TEST_LOGIC_RESET
                self._resets += 1
                tdi_value = tdo_value = bit_count = 0
                continue

            if previous == OcahJtagState.CAPTURE_IR:
                start_time = _time_ns()
                start_state = previous
                tdi_value = tdo_value = bit_count = 0
            elif previous == OcahJtagState.CAPTURE_DR:
                start_time = _time_ns()
                start_state = previous
                tdi_value = tdo_value = bit_count = 0

            if previous in (OcahJtagState.SHIFT_IR, OcahJtagState.SHIFT_DR):
                tdi_value |= (tdi & 0x1) << bit_count
                tdo_value |= (tdo & 0x1) << bit_count
                bit_count += 1

            nxt = next_jtag_state(previous, tms)
            if nxt != previous:
                self._state_changes += 1
            self._state = nxt

            if previous == OcahJtagState.SHIFT_IR and nxt == OcahJtagState.EXIT1_IR:
                pending_ir = tdi_value
                self._publish(
                    OcahJtagScanItem(
                        kind="IR",
                        tdi_value=tdi_value,
                        tdo_value=tdo_value,
                        bit_count=bit_count,
                        instruction=None,
                        start_time_ns=start_time,
                        end_time_ns=_time_ns(),
                        start_state=start_state,
                        end_state=nxt,
                        source=self.name,
                    )
                )
            elif previous == OcahJtagState.SHIFT_DR and nxt == OcahJtagState.EXIT1_DR:
                self._publish(
                    OcahJtagScanItem(
                        kind="DR",
                        tdi_value=tdi_value,
                        tdo_value=tdo_value,
                        bit_count=bit_count,
                        instruction=self._active_instruction,
                        start_time_ns=start_time,
                        end_time_ns=_time_ns(),
                        start_state=start_state,
                        end_state=nxt,
                        source=self.name,
                    )
                )

            if previous == OcahJtagState.UPDATE_IR:
                # Without a Shift-IR cycle the register latches its
                # device-specific Capture-IR pattern, unknown here.
                self._active_instruction = pending_ir
                pending_ir = None

    def _publish(self, item: OcahJtagScanItem) -> None:
        history = self._ir_history if item.is_ir else self._dr_history
        history.append(item)
        if len(history) > self._max_history:
            history.pop(0)

        callbacks = list(self._callbacks)
        callbacks += self._ir_callbacks if item.is_ir else self._dr_callbacks
        for callback in callbacks:
            try:
                callback(item)
            except AssertionError:
                # A checker verdict is never swallowed; the retained finding
                # still exists for aggregate mode.
                raise
            except Exception as exc:  # noqa: BLE001
                self.callback_errors += 1
                self.log.error("Exception in JTAG monitor callback %s: %s", callback, exc)
