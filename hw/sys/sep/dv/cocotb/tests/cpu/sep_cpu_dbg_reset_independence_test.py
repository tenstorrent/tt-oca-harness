# SPDX-License-Identifier: Apache-2.0
"""SEP CPU debug-reset domain-isolation test (PyUVM).

CPU-complex Phase-2 rep CPU debug-reset independence. OCAH provenance:
clock/sep_clock_uvm_reset_assertion_deassertion_test (dbg_rstb path) +
clock/sep_clock_uvm_jtag_clock_independence_test.

Proves the EL2 debugger reset ``dbg_rstb_i`` is reset-domain-isolated from the
system/CPU reset: pulsing ``dbg_rstb_i`` low (with ``rst_ni`` held released) must
NOT disturb the system reset ``sep_reset_n`` (``dbg_sep_reset_n_o``) or the CPU
warm reset ``sep_cpu_reset_n`` (``sep_cpu_reset_n_o``). This is the safety-relevant,
fully-frontdoor half of the spec property -- the positive "debug logic was reset"
confirmation needs JTAG-DTM debug-module access not wired on bare sep (deferred,
see the VPLAN card; no backdoor probe is added).

``dbg_rstb_i`` is a real ``sep`` primary input (sep.sv:24) that this tb now brings
out as a controllable top-level port (it was previously hardwired to ``rst_ni``);
``sep_base_test`` default-drives it released (1).

Checks (each asserts an exact value; ``self.rd`` resolves X->0, so the ==1
released checks fail on a stuck/X reset tree):
  CHK-BASELINE : with dbg_rstb_i high, sep_reset_n and sep_cpu_reset_n are released
                 (the isolation checker is not trivially always-true).
  CHK-ISO      : pulsing dbg_rstb_i low->high leaves BOTH sep_reset_n and
                 sep_cpu_reset_n released throughout -- a dbg_rstb-bleeds-into-
                 system-reset bug would drop them -> FAIL.
  CHK-LIVE     : non-vacuity contrast -- a real reset source (wdt_rst_ni_i low)
                 DOES drop sep_cpu_reset_n to 0 (so the observable is live, not
                 stuck-1), then restores; dbg_rstb left it released. This proves
                 CHK-ISO would catch a real bleed.

no_cpu / +skip_fuse_sense (reset-observable only; no AXI traffic, no OTP read).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

import pyuvm

from sep_base_test import sep_base_test

# Cycles to let the combinational/async reset path settle after a reset-input edge.
_SETTLE = 5


@pyuvm.test()
class sep_cpu_dbg_reset_independence_test(sep_base_test):
    """Pulse dbg_rstb_i and verify the system/CPU reset domain is undisturbed."""

    build_env = False

    async def _check_reset(self, sig, name: str, expected: int) -> None:
        """Assert a reset observable equals an exact value (X resolves to 0)."""
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
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "CHK-BASELINE sep_reset_n released", 1)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-BASELINE sep_cpu_reset_n released", 1)
        self.logger.info(
            "CHK-BASELINE PASS: both reset observables released with dbg_rstb_i high")

        # CHK-ISO: pulse dbg_rstb_i low (debug-logic reset) with rst_ni held high;
        # the system/CPU reset domain must stay released during AND after.
        dut.dbg_rstb_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "CHK-ISO during-pulse sep_reset_n", 1)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-ISO during-pulse sep_cpu_reset_n", 1)
        dut.dbg_rstb_i.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "CHK-ISO after-release sep_reset_n", 1)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-ISO after-release sep_cpu_reset_n", 1)
        self.logger.info(
            "CHK-ISO PASS: dbg_rstb_i pulse left sep_reset_n and sep_cpu_reset_n "
            "released (debug reset is domain-isolated)")

        # CHK-LIVE: non-vacuity contrast. A real reset source (wdt_rst_ni_i low)
        # MUST drop sep_cpu_reset_n -- proving the observable is live (not stuck-1)
        # and that CHK-ISO above would have caught a dbg_rstb->system-reset bleed.
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-LIVE wdt_rst_ni=0 drops sep_cpu_reset_n", 0)
        # The main SEP reset is CPU-reset-only-gated, so it stays released here.
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "CHK-LIVE wdt_rst_ni=0 leaves sep_reset_n", 1)
        dut.wdt_rst_ni_i.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o, "CHK-LIVE wdt_rst_ni=1 restores sep_cpu_reset_n", 1)
        self.logger.info(
            "CHK-LIVE PASS: sep_cpu_reset_n is reset-responsive (wdt drops it, "
            "dbg_rstb did not) -- CHK-ISO is non-vacuous")

        self.logger.info(
            "CPU debug-reset independence PASS: dbg_rstb_i reset-domain isolation verified "
            "(baseline / isolation / liveness-contrast)")
