# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Generic base sequence for DTP cocotb stimulus.

This class stays feature-agnostic. Feature-specific helpers live in
child base sequences such as ``dtp_jtag_base_test_seq``,
``dtp_debug_tdr_base_test_seq``, and ``dtp_jtag2axi_base_test_seq``.
The test assigns ``cfg`` before starting the sequence (dtp_base_test.plumb_scenario_seq).
The seed, loop, pattern, and step-logging helpers come from ``ocah_lib.OcahSequence``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from cocotb.triggers import ClockCycles
from env.dtp_dbg_disable import format_dbg_disable, full_dbg_disable, validate_dbg_disable
from env.dtp_env_cfg import DtpEnvCfg
from env.dtp_jtag_item import DtpJtagItem, DtpJtagOp
from env.dtp_types import DTP_IR_WIDTH, RESET_COUNT_CHECK_ID, DtpJtagInstr
from ocah_jtag_vip import OcahJtagState
from ocah_lib import OcahSequence


class DtpEvidenceRecorder(Protocol):
    """An evidence recorder: ``OcahChecker``, ``OcahJtagChecker`` or ``OcahAxiScoreboard``."""

    def expect_equal(
        self, check_id: str, observed: object, expected: object, *, context: str = ""
    ) -> bool: ...

    def expect_true(self, check_id: str, condition: object, *, context: str = "") -> bool: ...


class dtp_base_test_seq(OcahSequence):
    """Common DTP protocol building blocks; concrete sequences override body()."""

    def __init__(
        self,
        name: str = "dtp_base_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        # Assigned by the test (dtp_base_test.plumb_scenario_seq) before the sequence runs.
        self.cfg: DtpEnvCfg | None = None
        # DUT-confirmed TAP states and (state, TMS) transitions of this pass.
        self.visited_tap_states: set[OcahJtagState] = set()
        self.visited_tap_arcs: set[tuple[OcahJtagState, int]] = set()
        self.current_tap_state: OcahJtagState | None = None

    # --- quality logging / checking -----------------------------------------
    def log_banner(self, title: str) -> None:
        """Log a visible scenario boundary in simulation output."""
        self.log.info("=" * 70)
        self.log.info(title)
        self.log.info("=" * 70)

    def log_summary(self, title: str, **fields: object) -> None:
        """Log a compact end-of-scenario summary."""
        self.log.info("-" * 70)
        self.log.info("Summary: %s", title)
        for key, value in fields.items():
            self.log.info("  %s = %s", key, value)
        self.log.info("-" * 70)

    @staticmethod
    def check_equal(
        recorder: DtpEvidenceRecorder,
        check_id: str,
        observed: object,
        expected: object,
        *,
        context: str,
    ) -> None:
        """Record one named comparison on ``recorder`` and stop the pass on a mismatch.

        The FAIL record is the evidence; a recorder that does not fail fast
        keeps it for its summary.
        """
        if not recorder.expect_equal(check_id, observed, expected, context=context):
            raise AssertionError(f"{check_id} FAIL: {context}")

    @staticmethod
    def check_true(
        recorder: DtpEvidenceRecorder, check_id: str, condition: object, *, context: str
    ) -> None:
        """Record one named condition on ``recorder`` and stop the pass when it does not hold."""
        if not recorder.expect_true(check_id, condition, context=context):
            raise AssertionError(f"{check_id} FAIL: {context}")

    def check_reset_counted(self, counter: str, before: int, after: int, context: str) -> None:
        """``CHK-RESET-COUNT``: the tb_top assertion counter of a reset this
        sequence drove advanced by exactly one across the pulse, so a reset
        claim rests on a reset that happened.

        Each family base records it on the checker that family owns.
        """
        raise NotImplementedError(f"{type(self).__name__} records no {RESET_COUNT_CHECK_ID}")

    # --- bit helpers ---------------------------------------------------------
    @staticmethod
    def bit(value: int, bit_pos: int) -> int:
        """Return one bit from an integer."""
        return (value >> bit_pos) & 0x1

    @staticmethod
    def field(value: int, lsb: int, width: int) -> int:
        """Return a packed bit field."""
        return (value >> lsb) & ((1 << width) - 1)

    # --- low-level item issue ------------------------------------------------
    async def _send(self, **fields: object) -> DtpJtagItem:
        """Create, populate, and run a single DtpJtagItem; return it with results."""
        item = DtpJtagItem()
        await self.start_item(item)
        for key, value in fields.items():
            if not hasattr(item, key):
                raise AttributeError(f"DtpJtagItem has no field {key!r}")
            setattr(item, key, value)
        await self.finish_item(item)
        return item

    # --- reusable TAP steps --------------------------------------------------
    async def reset_tap(self) -> DtpJtagItem:
        """Drive the TAP to Test-Logic-Reset."""
        return await self._send(op=DtpJtagOp.RESET_FSM)

    async def tms_step(self, tms: int, *, tdi: int = 0) -> DtpJtagItem:
        """Drive one raw TMS cycle and return the observed DUT TAP state."""
        return await self._send(op=DtpJtagOp.TMS_STEP, tms=tms, tdi=tdi)

    async def load_ir(
        self,
        instr: DtpJtagInstr | int,
        *,
        back_to_rti: bool = True,
    ) -> DtpJtagItem:
        """Load a raw IR opcode and return captured previous-IR bits."""
        value = int(instr)
        self.log.info("Loading IR 0x%02x", value)
        item = await self._send(
            op=DtpJtagOp.SHIFT_IR,
            value=value,
            width=DTP_IR_WIDTH,
            back_to_rti=back_to_rti,
        )
        if back_to_rti:
            self.current_tap_state = OcahJtagState.RUN_TEST_IDLE
        return item

    async def shift_ir(
        self,
        value: int,
        width: int,
        *,
        back_to_rti: bool = True,
    ) -> DtpJtagItem:
        """Shift a raw IR value of any width and return captured TDO bits.

        The PTAP forwards its scan controls to the STAP chain on IR scans
        too, so a network-wide instruction scan (PTAP IR followed by the
        STAP chain and any spliced downstream TAP IRs) is longer than the
        PTAP's own IR; ``load_ir`` stays the plain 6-bit load.
        """
        item = await self._send(
            op=DtpJtagOp.SHIFT_IR,
            value=value,
            width=width,
            back_to_rti=back_to_rti,
        )
        if back_to_rti:
            self.current_tap_state = OcahJtagState.RUN_TEST_IDLE
        return item

    async def shift_dr(
        self,
        value: int,
        width: int,
        *,
        back_to_rti: bool = True,
    ) -> DtpJtagItem:
        """Shift raw DR data and return captured TDO bits."""
        item = await self._send(
            op=DtpJtagOp.SHIFT_DR,
            value=value,
            width=width,
            back_to_rti=back_to_rti,
        )
        if back_to_rti:
            self.current_tap_state = OcahJtagState.RUN_TEST_IDLE
        return item

    async def sample_observables(self) -> DtpJtagItem:
        """Sample exposed DUT observables through the JTAG driver."""
        return await self._send(op=DtpJtagOp.SAMPLE)

    async def assert_trst(self, cycles: int = 5) -> DtpJtagItem:
        """Assert active-low TRST_N and sample the TAP state."""
        return await self._send(op=DtpJtagOp.SET_TRST, value=0, cycles=cycles)

    async def deassert_trst(self, cycles: int = 1) -> DtpJtagItem:
        """Deassert TRST_N and sample the TAP state."""
        return await self._send(op=DtpJtagOp.SET_TRST, value=1, cycles=cycles)

    async def pulse_por(self, cycles: int = 5) -> DtpJtagItem:
        """Pulse power-on reset and sample the TAP state while reset is asserted."""
        before = self.cfg.tb_if.sample("por_assert_count")
        item = await self._send(op=DtpJtagOp.PULSE_POR, cycles=cycles)
        self.check_reset_counted(
            "por_assert_count",
            before,
            self.cfg.tb_if.sample("por_assert_count"),
            f"pulse_por cycles={cycles}",
        )
        return item

    async def read_idcode(self) -> DtpJtagItem:
        """Read the 32-bit IDCODE TDR."""
        return await self._send(op=DtpJtagOp.READ, reg="IDCODE")

    async def read_tdr(self, reg: str, shift_value: int = 0) -> int:
        """Read a named TDR, shifting caller-selected data through DR.

        The default shift value is zero, which is useful for catching unwanted
        R/W side effects. Tests that need to preserve writable bits should pass
        the expected retained value explicitly.
        """
        item = await self._send(op=DtpJtagOp.READ, reg=reg, value=shift_value)
        return item.result

    async def write_tdr(self, reg: str, value: int) -> None:
        """Write a named TDR through the shared JTAG driver."""
        await self._send(op=DtpJtagOp.WRITE, reg=reg, value=value)

    # --- lifecycle debug disables ---------------------------------------------
    # The DUT synchronizes dbg_disable_i through 2-stage TCK-domain flops, so
    # a disable change is only guaranteed visible after TCK has toggled.
    async def wait_dbg_disable_sync(self) -> None:
        """Settle a dbg_disable change: four idle TCK cycles (TB margin over
        the 2-stage synchronizers), then a short system-domain settle for the
        bridge-side logic behind them."""
        for _ in range(4):
            await self.tms_step(0)
        await self.wait_sys_cycles(4)

    async def set_dbg_disable(self, **bits: int) -> None:
        """Drive named dbg_disable fields (1 = disabled); others keep state."""
        named = validate_dbg_disable(bits)
        self.cfg.tb_if.set_dbg_disable(named)
        self.log.info("dbg_disable set %s", format_dbg_disable(named))
        await self.wait_dbg_disable_sync()

    async def set_dbg_disable_vector(self, values: Mapping[str, int]) -> None:
        """Drive all eleven dbg_disable fields; unnamed fields are enabled (0)."""
        await self.set_dbg_disable(**full_dbg_disable(values))

    async def enable_all_debug(self) -> None:
        """Clear every disable: full debug access."""
        await self.set_dbg_disable_vector({})

    async def disable_debug_bits(self, *names: str) -> None:
        """Assert one or more named disables; other fields keep state."""
        await self.set_dbg_disable(**{name: 1 for name in names})

    # --- system-domain helpers ----------------------------------------------
    async def wait_sys_cycles(self, cycles: int = 4) -> None:
        """Wait in the system-clock domain for registered DTP outputs to update."""
        await ClockCycles(self.cfg.tb_if.clk, cycles)

    async def pulse_system_reset(self, cycles: int = 5, *, context: str = "") -> None:
        """Pulse rst_n_i without asserting POR/TRST, preserving TAP accessibility."""
        before = self.cfg.tb_if.sample("sys_rst_assert_count")
        self.cfg.tb_if.sys_rst_n.value = 0
        await self.wait_sys_cycles(cycles)
        self.cfg.tb_if.sys_rst_n.value = 1
        await self.wait_sys_cycles(cycles)
        self.check_reset_counted(
            "sys_rst_assert_count",
            before,
            self.cfg.tb_if.sample("sys_rst_assert_count"),
            context or f"pulse_system_reset cycles={cycles}",
        )

    async def body(self) -> None:
        raise NotImplementedError("override body() in a concrete test sequence")
