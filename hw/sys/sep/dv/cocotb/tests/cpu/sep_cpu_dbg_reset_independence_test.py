# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP CPU reset-observable baseline and liveness (PyUVM).

CPU-complex reset-observable baseline and liveness. reference provenance:
clock/sep_clock_uvm_reset_assertion_deassertion_test (dbg_rstb path) +
clock/sep_clock_uvm_jtag_clock_independence_test.

Proves the two reset observables are released at rest and that the CPU
observable is live under a real reset source. ``dbg_rstb_i`` isolation is not
claimed: in ``lsu_stub_all_live`` the pin has no netlist path to either
observable, so a pulse-and-check assert cannot fail.

``dbg_rstb_i`` is a real ``sep`` primary input (sep.sv) brought out as a
controllable top-level port; ``sep_base_test`` default-drives it released (1).

Checks (each asserts an exact value; ``self.rd`` raises on X/Z, so no check
passes on an undriven reset tree):
  CHK-BASELINE : with dbg_rstb_i high, sep_reset_n and sep_cpu_reset_n are released.
  CHK-LIVE     : a real reset source (wdt_rst_ni_i low) drops sep_cpu_reset_n
                 to 0, then restores it -- so the observable is live, not stuck-1.

Closing the isolation claim needs a cpu run-mode so the pin reaches ``sep_cpu``
and a specification statement to check it against. Do not add a pulse-and-check
without both.

no_cpu / +skip_fuse_sense (reset-observable only; no AXI traffic, no OTP read).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test

# Cycles to let the combinational/async reset path settle after a reset-input edge.
_SETTLE = 5


@pyuvm.test()
class sep_cpu_dbg_reset_independence_test(sep_base_test):
    """Baseline release and liveness of the CPU reset observable."""

    build_env = False

    async def _check_reset(self, sig, name: str, expected: int) -> None:
        """Assert a reset observable equals an exact value.

        ``rd`` raises on an X/Z bit, so neither ``== 0`` nor ``== 1`` can hold
        for an observable nothing drives.
        """
        val = self.rd(sig)
        if val != expected:
            raise AssertionError(f"{name}: expected {expected}, got {val}")
        self.logger.info("PASS: %s == %d", name, expected)

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Baseline bring-up: dbg_rstb_i + wdt_rst_ni_i default to 1 (released),
        # fabric released after fuse-sense-done.
        await self.bring_up_no_cpu()

        # CHK-BASELINE: dbg_rstb_i high -> system/CPU reset domain released.
        await self._check_reset(dut.dbg_sep_reset_n_o, "CHK-BASELINE sep_reset_n released", 1)
        await self._check_reset(dut.sep_cpu_reset_n_o, "CHK-BASELINE sep_cpu_reset_n released", 1)
        self.logger.info("CHK-BASELINE PASS: both reset observables released with dbg_rstb_i high")

        # No CHK-ISO: in lsu_stub_all_live dbg_rstb_i has no netlist path to either
        # observable (module docstring), so a pulse-and-check could not fail.

        # CHK-LIVE: a real reset source (wdt_rst_ni_i low) MUST drop sep_cpu_reset_n,
        # proving the observable is live rather than stuck at 1.
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-LIVE wdt_rst_ni=0 drops sep_cpu_reset_n", 0
        )
        # The main SEP reset is CPU-reset-only-gated, so it stays released here.
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "CHK-LIVE wdt_rst_ni=0 leaves sep_reset_n", 1
        )
        dut.wdt_rst_ni_i.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-LIVE wdt_rst_ni=1 restores sep_cpu_reset_n", 1
        )
        self.logger.info(
            "CHK-LIVE PASS: sep_cpu_reset_n is reset-responsive (wdt drops it and "
            "restores it), so the observable is live rather than stuck at 1"
        )

        self.logger.info(
            "CPU debug-reset observables PASS: baseline released + reset-responsive "
            "(baseline / liveness-contrast; dbg_rstb isolation NOT covered)"
        )
