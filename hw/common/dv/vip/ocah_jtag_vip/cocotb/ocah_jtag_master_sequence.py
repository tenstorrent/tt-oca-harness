# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence-level API over the JTAG driver with named checker evidence.

`OcahJtagMasterSequence` provides the scenario building blocks tests repeat around
the raw driver: reset-to-TLR, checked IDCODE reads, reference-model BYPASS
latency checks, and monitor-backed scan-length evidence. Every checked
operation emits `CHK-*` named evidence through the wrapped `OcahJtagChecker`,
so a sequence-driven test gets the same evidence grammar as hand-wired
checker calls.

Pin-level scope: operations here rely only on the JTAG pins (driven TDI/TMS,
captured TDO). Checks that need a DUT-side TAP-state observable (e.g.
per-step `CHK-TAP-STATE`) stay in DUT-level sequences that can sample it.
"""

from __future__ import annotations

from .ocah_jtag_checker import OcahJtagChecker
from .ocah_jtag_master_driver import OcahJtagMasterDriver
from .ocah_jtag_master_monitor import OcahJtagMasterMonitor
from .ocah_jtag_ref_model import TLR_TMS_ONES
from .ocah_jtag_state import OcahJtagState

__all__ = ["OcahJtagMasterSequence"]

IDCODE_DR_WIDTH = 32


class OcahJtagMasterSequence:
    """Checked scenario operations over one TAP driver.

    This class is the VIP's test-facing stimulus surface: tests drive the TAP
    through it (or a DUT sequence layer built on it), never through the raw
    driver. Missing operations get added here first.
    """

    def __init__(
        self,
        tap: OcahJtagMasterDriver,
        checker: OcahJtagChecker | None = None,
        *,
        monitor: OcahJtagMasterMonitor | None = None,
    ) -> None:
        self.tap = tap
        self.checker = checker or OcahJtagChecker(
            name=f"{getattr(tap, 'name', 'OcahJtag')}.seq_checker"
        )
        self.monitor = monitor

    # ------------------------------------------------------------------
    # Pass-through stimulus operations (the sequence-level scan API).
    # ------------------------------------------------------------------

    async def reset_to_tlr(self, cycles: int = 10) -> None:
        """Reset the TAP and re-baseline the checker's reference model."""
        await self.tap.reset_tap(cycles=max(cycles, TLR_TMS_ONES))
        self.checker.ref_model.reset()

    async def step(self, tms: int, tdi: int = 0) -> int:
        """Drive one TCK cycle with ``tms``/``tdi`` and return sampled TDO."""
        return await self.tap.step(tms, tdi)

    async def step_tms(self, tms: int) -> int:
        """Drive one raw TMS cycle and return sampled TDO."""
        return await self.tap.step_tms(tms)

    def sync_model(self, state: OcahJtagState | str, *, instruction: int | None = None) -> None:
        """Re-align the driver's tracked state and the checker's reference model."""
        self.tap.sync_model(state, instruction=instruction)
        self.checker.ref_model.sync(state)

    async def assert_trst(self, *, tck_cycles: int = 1) -> None:
        """Assert TRST with ``tck_cycles`` of TMS high and re-baseline the reference model."""
        await self.tap.assert_trst(tck_cycles=tck_cycles)
        self.checker.ref_model.reset()

    async def release_trst(self, *, tck_cycles: int = 0) -> None:
        """Release TRST, then step ``tck_cycles`` of TMS high through the reference model."""
        await self.tap.release_trst(tck_cycles=tck_cycles)
        for _ in range(max(int(tck_cycles), 0)):
            self.checker.ref_model.step(1)

    async def goto_state(self, state) -> None:
        """Navigate to a TAP state using a shortest TMS path."""
        await self.tap.goto_state(state)

    async def shift_ir(
        self,
        value: int,
        width: int | None = None,
        *,
        back_to_rti: bool = False,
    ) -> int:
        """Shift an instruction into IR and return captured TDO bits."""
        return await self.tap.shift_ir(value, width, back_to_rti=back_to_rti)

    async def shift_dr(
        self,
        value: int,
        width: int,
        *,
        back_to_rti: bool = False,
    ) -> int:
        """Shift a pattern through DR and return captured TDO bits."""
        return await self.tap.shift_dr(value, width, back_to_rti=back_to_rti)

    # ------------------------------------------------------------------
    # Checked scenario operations (emit CHK-* named evidence).
    # ------------------------------------------------------------------

    async def read_idcode_checked(
        self,
        expected_idcode: int,
        *,
        context: str = "",
    ) -> int:
        """Read IDCODE and emit CHK-IDCODE-RAW / CHK-IDCODE-MARKER evidence."""
        idcode = await self.tap.read_idcode()
        self.checker.expect_equal("CHK-IDCODE-RAW", idcode, expected_idcode, context=context)
        self.checker.expect_equal(
            "CHK-IDCODE-MARKER",
            idcode & 0x1,
            1,
            context=f"raw=0x{idcode:08x} {context}".strip(),
        )
        return idcode

    async def check_bypass_latency(
        self,
        pattern: int,
        width: int,
        *,
        capture_bit: int = 0,
        context: str = "",
    ) -> int:
        """Scan through BYPASS and emit CHK-BYPASS-LATENCY evidence."""
        await self.tap.bypass()
        observed = await self.tap.shift_dr(pattern, width, back_to_rti=True)
        self.checker.check_bypass_latency(
            observed,
            pattern=pattern,
            width=width,
            capture_bit=capture_bit,
            context=context,
        )
        return observed

    def check_last_scan_length(
        self, *, is_ir: bool, expected_width: int, context: str = ""
    ) -> None:
        """Emit CHK-SCAN-*-LEN for the newest monitor-reconstructed scan."""
        if self.monitor is None:
            raise RuntimeError("scan-length checks require a monitor")
        items = self.monitor.get_ir_transactions() if is_ir else self.monitor.get_dr_transactions()
        if not items:
            raise AssertionError(
                f"no reconstructed {'IR' if is_ir else 'DR'} scan observed ({context})"
            )
        self.checker.check_scan_length(items[-1], expected_width=expected_width, context=context)

    def finalize(self) -> None:
        """Finalize retained findings and required named evidence."""
        self.checker.finalize()
