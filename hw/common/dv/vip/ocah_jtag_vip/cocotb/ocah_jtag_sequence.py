# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Sequence-level API over the JTAG driver with named checker evidence.

`OcahJtagSequence` provides the scenario building blocks tests repeat around
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
from .ocah_jtag_driver import OcahJtagTap
from .ocah_jtag_monitor import OcahJtagMonitor
from .ocah_jtag_ref_model import TLR_TMS_ONES

__all__ = ["OcahJtagSequence"]

IDCODE_DR_WIDTH = 32


class OcahJtagSequence:
    """Checked scenario operations over one TAP driver."""

    def __init__(
        self,
        tap: OcahJtagTap,
        checker: OcahJtagChecker,
        *,
        monitor: OcahJtagMonitor | None = None,
    ) -> None:
        self.tap = tap
        self.checker = checker
        self.monitor = monitor

    async def reset_to_tlr(self, cycles: int = 10) -> None:
        """Reset the TAP and re-baseline the checker's reference model."""
        await self.tap.reset_tap(cycles=max(cycles, TLR_TMS_ONES))
        self.checker.ref_model.reset()

    async def read_idcode_checked(
        self,
        expected_idcode: int,
        *,
        context: str = "",
    ) -> int:
        """Read IDCODE and emit CHK-IDCODE-RAW / CHK-IDCODE-MARKER evidence."""
        idcode = await self.tap.read_idcode()
        self.checker.expect_equal(
            "CHK-IDCODE-RAW", idcode, expected_idcode, context=context
        )
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

    def check_last_scan_length(self, *, is_ir: bool, expected_width: int, context: str = "") -> None:
        """Emit CHK-SCAN-*-LEN for the newest monitor-reconstructed scan."""
        if self.monitor is None:
            raise RuntimeError("scan-length checks require a monitor")
        items = (
            self.monitor.get_ir_transactions()
            if is_ir
            else self.monitor.get_dr_transactions()
        )
        if not items:
            raise AssertionError(
                f"no reconstructed {'IR' if is_ir else 'DR'} scan observed ({context})"
            )
        self.checker.check_scan_length(
            items[-1], expected_width=expected_width, context=context
        )

    def finalize(self) -> None:
        """Finalize retained findings and required named evidence."""
        self.checker.finalize()
