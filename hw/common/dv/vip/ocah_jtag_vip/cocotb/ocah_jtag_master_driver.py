# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCAH-stable IEEE 1149.1 TAP driver (the VIP's active driver component)."""

from __future__ import annotations

import logging
from random import Random
from typing import Any

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, Timer
from cocotb.utils import get_sim_time
from cocotbext.jtag import JTAGBus, JTAGDriver

from .ocah_jtag_device import OcahJtagDevice
from .ocah_jtag_state import (
    OcahJtagState,
    coerce_jtag_state,
    jtag_tms_path,
    next_jtag_state,
    random_jtag_state,
)

__all__ = ["OcahJtagMasterDriver", "OcahJtagMasterDriverError"]

IDCODE_OPCODE: int = 0x01
IDCODE_DR_WIDTH: int = 32

_PLUSARG_TCK_PERIOD = "JTAG_TCK_PERIOD_NS"
_PLUSARG_IR_WIDTH = "JTAG_IR_WIDTH"

_DEFAULT_SIGNAL_MAP: dict[str, str] = {
    "tck": "tck",
    "tms": "tms",
    "tdi": "tdi",
    "tdo": "tdo",
    "trst": "trst",
    "tdo_oen": "tdo_oen",
}


class OcahJtagMasterDriverError(RuntimeError):
    """Raised when a TAP operation encounters an unexpected condition."""


def _read_plusarg(name: str, default: int) -> int:
    try:
        raw = cocotb.plusargs.get(name)
        if raw is not None:
            return int(raw)
    except Exception:  # noqa: BLE001 - plusargs may be unavailable in import smoke tests.
        pass
    return default


def _logic_int(signal, default: int = 0) -> int:
    """Read a JTAG pin as int; missing pins and X/Z stay ``default``.

    Shared across DUT trees: a pre-TAP-reset X on TDO/TRST must not hard-fail
    every JTAG sequence. Callers that need a strict sample assert separately.
    """
    try:
        val = signal.value
    except Exception:  # noqa: BLE001 - missing optional pins (e.g. trst) stay default.
        return default
    if hasattr(val, "is_resolvable") and not val.is_resolvable:
        return default
    try:
        return int(val)
    except Exception:  # noqa: BLE001 - X/Z or non-integer stays default.
        return default


async def _timer(value: float | int, unit: str) -> None:
    await Timer(value, unit=unit)


class _JtagIntfProxy:
    """Attribute proxy for logical-to-physical signal-name remapping."""

    def __init__(self, intf, signal_map: dict[str, str]):
        object.__setattr__(self, "_intf", intf)
        object.__setattr__(self, "_map", signal_map)
        object.__setattr__(self, "_log", logging.getLogger("OcahJtagMasterDriver._intf"))

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


class OcahJtagMasterDriver:
    """OCAH-stable active TAP driver.

    The wrapper uses `cocotbext-jtag` `JTAGBus` for bus binding and keeps the
    OCAH raw TAP stepping/scanning semantics required by DTP.
    """

    def __init__(
        self,
        jtag_intf,
        *,
        name: str = "OcahJtagMasterDriver",
        tck_period_ns: int = 10,
        ir_width: int = 5,
        tap_type: str = "ptap",
        signal_map: dict[str, str] | None = None,
        time_unit: str = "ns",
        trst_active_high: bool = False,
    ) -> None:
        self.name = name
        self.tap_type = tap_type
        self.log = logging.getLogger(name)
        self._time_unit = time_unit
        # IEEE 1149.1 TRST* is active-low by default. Some TBs (e.g. SMC CPU
        # TAP ``*_reset``) expose an active-high reset; invert drive polarity.
        self._trst_active_high = bool(trst_active_high)

        tck_period_ns = _read_plusarg(_PLUSARG_TCK_PERIOD, tck_period_ns)
        ir_width = _read_plusarg(_PLUSARG_IR_WIDTH, ir_width)
        self._tck_period_ns = int(tck_period_ns)
        self._ir_width = int(ir_width)
        self._half_period = self._tck_period_ns / 2
        # Hold time for TMS/TDI after the TCK falling edge (see _cycle).
        self._quarter_period = self._tck_period_ns / 4
        self._bypass_opcode = (1 << self._ir_width) - 1

        self._signal_map = dict(_DEFAULT_SIGNAL_MAP)
        if signal_map:
            self._signal_map.update(signal_map)

        if isinstance(jtag_intf, JTAGBus):
            self.bus = jtag_intf
            self._intf = jtag_intf
        else:
            self._intf = _JtagIntfProxy(jtag_intf, self._signal_map)
            self.bus = JTAGBus.from_entity(self._intf)

        self._state = OcahJtagState.TEST_LOGIC_RESET
        self._current_instruction: int | None = None
        self._devices: list[OcahJtagDevice] = []
        self._stats_ir = 0
        self._stats_dr = 0
        self._stats_resets = 0
        self._stats_tms = 0

        self.log.info(
            "%s: initialized tap_type=%s ir_width=%d tck_period=%dns",
            self.name,
            self.tap_type,
            self._ir_width,
            self._tck_period_ns,
        )

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        *,
        name: str = "OcahJtagMasterDriver",
        tck_period_ns: int = 10,
        ir_width: int = 5,
        tap_type: str = "ptap",
        trst_signal: str | None = "trst",
        **kwargs: Any,
    ) -> "OcahJtagMasterDriver":
        """Construct from flattened signals with the given prefix.

        ``trst_signal`` selects the DUT suffix for the optional reset net
        (bus attribute remains ``trst``). Use ``\"reset\"`` for TBs that expose
        ``{prefix}_reset`` instead of ``{prefix}_trst``. Pass ``None`` to omit
        the reset net entirely.

        Note: ``cocotbext.jtag.JTAGBus`` hard-codes ``optional_signals=['trst']``,
        so non-default reset names are remapped through ``signal_map`` rather
        than Bus kwargs.
        """
        if trst_signal in (None, "trst"):
            bus = JTAGBus.from_prefix(dut, prefix)
            return cls(
                bus,
                name=name,
                tck_period_ns=tck_period_ns,
                ir_width=ir_width,
                tap_type=tap_type,
                **kwargs,
            )

        class _PrefixedNamespace:
            def __getattr__(self, signal_name: str):
                return getattr(dut, f"{prefix}_{signal_name}")

        assert trst_signal is not None
        return cls(
            _PrefixedNamespace(),
            name=name,
            tck_period_ns=tck_period_ns,
            ir_width=ir_width,
            tap_type=tap_type,
            signal_map={"trst": trst_signal},
            **kwargs,
        )

    @classmethod
    def from_bus(
        cls,
        bus: JTAGBus,
        *,
        name: str = "OcahJtagMasterDriver",
        tck_period_ns: int = 10,
        ir_width: int = 5,
        tap_type: str = "ptap",
        **kwargs: Any,
    ) -> "OcahJtagMasterDriver":
        """Construct from an existing `cocotbext-jtag` bus object."""
        return cls(
            bus,
            name=name,
            tck_period_ns=tck_period_ns,
            ir_width=ir_width,
            tap_type=tap_type,
            **kwargs,
        )

    @property
    def backend_bus(self) -> JTAGBus:
        """Return the underlying `cocotbext-jtag` bus for advanced debug only."""
        return self.bus

    def create_backend_driver(self) -> JTAGDriver:
        """Create a `cocotbext-jtag` driver for advanced experiments only.

        Normal OCAH tests should use the stable methods on this wrapper. The
        backend driver starts its own TCK generator, so do not mix it with active
        raw stepping on the same TAP.
        """
        driver = JTAGDriver(self.bus, period=self._tck_period_ns, unit=self._time_unit)
        for device in self._devices:
            driver.add_device(device.to_backend())
        return driver

    def _drive_trst(self, *, asserted: bool) -> None:
        """Drive the optional TRST/reset net with configured polarity."""
        if not hasattr(self.bus, "trst"):
            return
        if self._trst_active_high:
            self.bus.trst.value = 1 if asserted else 0
        else:
            self.bus.trst.value = 0 if asserted else 1

    def _trst_is_asserted(self) -> bool:
        if not hasattr(self.bus, "trst"):
            return False
        level = _logic_int(self.bus.trst, 0 if self._trst_active_high else 1)
        return bool(level) if self._trst_active_high else level == 0

    def init_signals(self) -> None:
        """Drive TAP outputs to their idle/safe values before traffic."""
        self.bus.tck.value = 0
        self.bus.tms.value = 1
        self.bus.tdi.value = 0
        self._drive_trst(asserted=False)
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self.log.debug("%s: signals initialized", self.name)

    def add_device(self, device: OcahJtagDevice) -> None:
        """Add a plain OCAH JTAG device/register map."""
        if not isinstance(device, OcahJtagDevice):
            raise TypeError("add_device expects OcahJtagDevice")
        self._devices.append(device)

    async def reset_tap(self, cycles: int = 10) -> None:
        """Drive the TAP to Test-Logic-Reset deterministically."""
        cycles = max(int(cycles), 5)
        self.log.info("%s: reset_tap cycles=%d", self.name, cycles)
        self._drive_trst(asserted=True)
        for _ in range(cycles):
            await self._cycle(1, 0)
        self._drive_trst(asserted=False)
        self._state = OcahJtagState.TEST_LOGIC_RESET
        self._current_instruction = None
        self._stats_resets += 1

    async def step(self, tms: int, tdi: int = 0) -> int:
        """Drive one TCK cycle with ``tms``/``tdi`` and return the sampled TDO.

        The tracked TAP state follows the TMS bit, so a scan shifted one bit
        at a time stays in step with ``get_current_state()``.
        """
        return await self._cycle(int(tms) & 0x1, int(tdi) & 0x1)

    async def step_tms(self, tms: int) -> int:
        """Drive one TCK cycle with TDI low and return the sampled TDO."""
        return await self.step(tms, 0)

    def sync_model(self, state: OcahJtagState | str, *, instruction: int | None = None) -> None:
        """Declare the TAP state after movement this driver did not drive.

        A power-on reset or a reset pin outside the bound TAP moves the
        controller without a TCK cycle on this bus; the bench declares the
        resulting state here so ``goto_state()`` plans from the true
        controller state. ``instruction`` is the IR content after the
        movement; ``None`` records it as unknown.
        """
        self._state = coerce_jtag_state(state)
        self._current_instruction = instruction
        self.log.debug("%s: sync_model state=%s", self.name, self._state.name)

    async def assert_trst(self, *, tck_cycles: int = 1) -> None:
        """Assert the bound TRST net and run ``tck_cycles`` TCK cycles with TMS high.

        The tracked state becomes Test-Logic-Reset and the tracked instruction
        is cleared.
        """
        await self._trst_level(asserted=True, tck_cycles=tck_cycles)

    async def release_trst(self, *, tck_cycles: int = 0) -> None:
        """Release the bound TRST net, then run ``tck_cycles`` TCK cycles with TMS high."""
        await self._trst_level(asserted=False, tck_cycles=tck_cycles)

    async def _trst_level(self, *, asserted: bool, tck_cycles: int) -> None:
        if not hasattr(self.bus, "trst"):
            raise OcahJtagMasterDriverError(f"{self.name}: no TRST net is bound")
        self._drive_trst(asserted=asserted)
        for _ in range(max(int(tck_cycles), 0)):
            await self._cycle(1, 0)
        if asserted:
            self._state = OcahJtagState.TEST_LOGIC_RESET
            self._current_instruction = None
            self._stats_resets += 1
        self.log.debug("%s: trst asserted=%s tck_cycles=%d", self.name, asserted, int(tck_cycles))

    async def goto_state(self, state) -> None:
        """Navigate to a TAP state using a shortest TMS path."""
        target = coerce_jtag_state(state)
        path = jtag_tms_path(self._state, target)
        self.log.debug(
            "%s: goto_state %s -> %s path=%s", self.name, self._state.name, target.name, path
        )
        for tms in path:
            await self.step_tms(tms)

    async def random_tms_walk(self, cycles: int, rng: Random) -> OcahJtagState:
        """Drive a reproducible random TMS walk."""
        for _ in range(int(cycles)):
            await self.step_tms(rng.randint(0, 1))
        return self._state

    async def goto_random_state(
        self,
        rng: Random,
        *,
        exclude: set[OcahJtagState] | None = None,
    ) -> OcahJtagState:
        """Choose and navigate to a reproducible random TAP state."""
        target = random_jtag_state(rng, exclude=exclude)
        await self.goto_state(target)
        return target

    async def shift_ir(
        self, value: int, width: int | None = None, *, back_to_rti: bool = False
    ) -> int:
        """Shift an integer into IR and return captured TDO bits."""
        width = self._ir_width if width is None else int(width)
        if width <= 0:
            raise OcahJtagMasterDriverError(f"{self.name}: shift_ir width must be > 0")

        await self.goto_state(OcahJtagState.SHIFT_IR)
        captured = await self._shift_bits(value, width, end_tms=1)
        await self.step_tms(1)  # EXIT1_IR -> UPDATE_IR
        self._current_instruction = int(value) & ((1 << width) - 1)
        if back_to_rti:
            await self.step_tms(0)  # UPDATE_IR -> RUN_TEST_IDLE
        else:
            await self.step_tms(1)  # UPDATE_IR -> SELECT_DR_SCAN
        self._stats_ir += 1
        return captured

    async def shift_dr(self, value: int, width: int, *, back_to_rti: bool = False) -> int:
        """Shift an integer into DR and return captured TDO bits."""
        width = int(width)
        if width < 0:
            raise OcahJtagMasterDriverError(f"{self.name}: shift_dr width must be >= 0")
        if width == 0:
            return 0

        await self.goto_state(OcahJtagState.SHIFT_DR)
        captured = await self._shift_bits(value, width, end_tms=1)
        await self.step_tms(1)  # EXIT1_DR -> UPDATE_DR
        if back_to_rti:
            await self.step_tms(0)  # UPDATE_DR -> RUN_TEST_IDLE
        else:
            await self.step_tms(1)  # UPDATE_DR -> SELECT_DR_SCAN
        self._stats_dr += 1
        return captured

    async def read(self, reg: str, *, device: int = 0, shift_value: int = 0) -> int:
        """Read a named JTAG register through a registered device map."""
        tap_device = self._device(device)
        desc = tap_device.reg(reg)
        await self.shift_ir(desc.opcode, width=tap_device.ir_width, back_to_rti=False)
        value = await self.shift_dr(shift_value, width=desc.width, back_to_rti=True)
        await self._idle_tck(tap_device.idle_delay)
        return value

    async def write(self, reg: str, value: int, *, device: int = 0) -> None:
        """Write a named JTAG register through a registered device map."""
        tap_device = self._device(device)
        desc = tap_device.reg(reg)
        await self.shift_ir(desc.opcode, width=tap_device.ir_width, back_to_rti=False)
        await self.shift_dr(value, width=desc.width, back_to_rti=True)
        await self._idle_tck(tap_device.idle_delay)

    async def read_idcode(self, *, device: int = 0) -> int:
        """Read a 32-bit IDCODE value as a plain integer."""
        if self._devices:
            idcode = await self.read("IDCODE", device=device)
        else:
            await self.goto_state(OcahJtagState.RUN_TEST_IDLE)
            await self.shift_ir(IDCODE_OPCODE, self._ir_width, back_to_rti=False)
            idcode = await self.shift_dr(0, IDCODE_DR_WIDTH, back_to_rti=True)

        if idcode == 0xFFFF_FFFF:
            raise OcahJtagMasterDriverError(
                f"{self.name}: read_idcode returned 0xffffffff; possible bypass or no device"
            )
        self.log.info("%s: IDCODE = 0x%08x", self.name, idcode)
        return idcode

    async def bypass(self) -> None:
        """Load the all-ones BYPASS instruction and return to Run-Test/Idle."""
        await self.shift_ir(self._bypass_opcode, self._ir_width, back_to_rti=True)

    def decode_idcode(self, value: int) -> dict[str, int]:
        """Decode standard IEEE 1149.1 IDCODE fields."""
        return {
            "marker": int(value) & 0x1,
            "manufacturer": (int(value) >> 1) & 0x7FF,
            "part_number": (int(value) >> 12) & 0xFFFF,
            "version": (int(value) >> 28) & 0xF,
        }

    def get_current_state(self) -> OcahJtagState:
        """Return the wrapper's tracked TAP state."""
        return self._state

    def get_statistics(self) -> dict[str, Any]:
        """Return plain operational statistics."""
        return {
            "ir_scans": self._stats_ir,
            "dr_scans": self._stats_dr,
            "resets": self._stats_resets,
            "tms_steps": self._stats_tms,
            "tck_period_ns": self._tck_period_ns,
            "ir_width": self._ir_width,
            "tap_type": self.tap_type,
            "current_state": self._state.name,
            "current_instruction": self._current_instruction,
        }

    async def _idle_tck(self, cycles: int) -> None:
        for _ in range(max(int(cycles), 0)):
            await self.step_tms(0)

    def _device(self, index: int) -> OcahJtagDevice:
        try:
            return self._devices[int(index)]
        except IndexError as exc:
            raise OcahJtagMasterDriverError(
                f"{self.name}: no JTAG device registered at index {index}"
            ) from exc

    async def _shift_bits(self, value: int, width: int, *, end_tms: int) -> int:
        captured = 0
        mask = (1 << width) - 1
        shifted = int(value) & mask
        for bit_idx in range(width):
            tdi = (shifted >> bit_idx) & 0x1
            tms = int(end_tms) if bit_idx == width - 1 else 0
            tdo = await self._cycle(tms, tdi)
            captured |= (tdo & 0x1) << bit_idx
        return captured

    async def _cycle(self, tms: int, tdi: int) -> int:
        previous = self._state
        # The previous cycle ends by driving TCK low without advancing time, so
        # depositing the next TMS/TDI immediately would land in the same
        # simulator timestep as that falling edge and race any negedge-clocked
        # target logic whose data input follows TDI/TMS combinationally (e.g.
        # the IEEE 1149.1 TDO retimer behind a zero-length scan loop). Like a
        # physical tester, hold the previous values through the falling edge
        # and change them a quarter period into the low phase.
        await _timer(self._quarter_period, self._time_unit)
        self.bus.tms.value = int(tms) & 0x1
        self.bus.tdi.value = int(tdi) & 0x1
        self.bus.tck.value = 0
        await _timer(self._half_period - self._quarter_period, self._time_unit)
        # IEEE 1149.1 targets update TDO on the falling edge. Sample it in the
        # low phase before the next rising edge advances the TAP state; sampling
        # after that edge corrupts the final scan bit when TMS exits Shift-IR/DR.
        await ReadOnly()
        tdo = _logic_int(self.bus.tdo)
        await NextTimeStep()
        self.bus.tck.value = 1
        await _timer(self._half_period, self._time_unit)
        self.bus.tck.value = 0
        self._state = next_jtag_state(previous, tms)
        if self._trst_is_asserted():
            self._state = OcahJtagState.TEST_LOGIC_RESET
        self._stats_tms += 1
        return tdo

    def _sim_time_ns(self) -> float:
        try:
            return float(get_sim_time(units="ns"))
        except TypeError:
            return float(get_sim_time(unit="ns"))
