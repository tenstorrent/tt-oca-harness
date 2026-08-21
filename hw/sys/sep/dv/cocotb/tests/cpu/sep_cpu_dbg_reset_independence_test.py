# SPDX-License-Identifier: Apache-2.0
"""SEP CPU debug-reset domain-isolation test (PyUVM).

CPU-complex Phase-2 rep CPU debug-reset independence. reference provenance:
clock/sep_clock_uvm_reset_assertion_deassertion_test (dbg_rstb path) +
clock/sep_clock_uvm_jtag_clock_independence_test.

Proves the EL2 debugger reset ``dbg_rstb_i`` is reset-domain-isolated from the
system/CPU reset: pulsing ``dbg_rstb_i`` low (with ``rst_ni`` held released) must
NOT disturb the system reset ``sep_reset_n`` (``dbg_sep_reset_n_o``) or the CPU
warm reset ``sep_cpu_reset_n`` (``sep_cpu_reset_n_o``). This is the safety-relevant,
fully-frontdoor half of the spec property -- the positive "debug logic was reset"
confirmation needs JTAG-DTM debug-module access not wired on bare sep (deferred,
see the VPLAN card; no backdoor probe is added).

``dbg_rstb_i`` is a real ``sep`` primary input (sep.sv:24) brought out as a
controllable top-level port; ``sep_base_test`` default-drives it released (1).

Checks (each asserts an exact value; ``self.rd`` resolves X->0, so the ==1
released checks fail on a stuck/X reset tree):
  CHK-BASELINE : with dbg_rstb_i high, sep_reset_n and sep_cpu_reset_n are released
                 (the isolation checker is not trivially always-true).
  CHK-LIVE     : a real reset source (wdt_rst_ni_i low) DOES drop sep_cpu_reset_n
                 to 0, then restores it -- so the observable is live, not stuck-1.

NOT covered: the dbg_rstb_i isolation claim itself. In this build the pin has no
path to either observable, so a pulse-and-check assert cannot fail. See the long
note in run_scenario for why, and what closing it would take. Do not re-add such
a check without both a run-mode change and a positive debug-domain observable.

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

        # No CHK-ISO. This test elaborates lsu_stub_all_live, whose CPU stub
        # declares dbg_rstb_i and never reads it. Against the real CPU, sep.sv
        # routes the pin only into sep_cpu, and sep_reset_ctrl -- which produces
        # both observables -- has no dbg_rstb port. There is no netlist path from
        # the stimulus to either signal, so a pulse-and-check would be CHK-BASELINE
        # with a no-op write in between. Closing the isolation claim needs a cpu
        # run-mode (so the pin reaches sep_cpu) and a positive debug-domain
        # observable; that is an open item in the plan.

        # CHK-LIVE: a real reset source (wdt_rst_ni_i low) MUST drop sep_cpu_reset_n,
        # proving the observable is live rather than stuck at 1.
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
            "CHK-LIVE PASS: sep_cpu_reset_n is reset-responsive (wdt drops it and "
            "restores it), so the observable is live rather than stuck at 1")

        self.logger.info(
            "CPU debug-reset observables PASS: baseline released + reset-responsive "
            "(baseline / liveness-contrast; dbg_rstb isolation NOT covered)")
