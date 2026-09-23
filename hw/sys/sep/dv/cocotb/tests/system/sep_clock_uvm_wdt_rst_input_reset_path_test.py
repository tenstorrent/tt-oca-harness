# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP WDT reset-input path test (PyUVM).

OSS port of the reference suite ``sep_clock_uvm_wdt_rst_input_reset_path_test``
(SEP side). Verifies the SEP WDT reset-INPUT path:

    wdt_rst_ni -> CPU warm reset, system reset isolated

VPLAN card ``sep_clock_uvm_wdt_rst_input_reset_path_test``: driving the SEP
primary input ``wdt_rst_ni_i`` drops and releases ``sep_cpu_reset_n`` only.
``wdt_rst_ni_i`` has no fan-out to the system-reset observable, so
``sep_reset_n`` stays released. Frontdoor: the tb drives the real
``wdt_rst_ni`` DUT input and observes ``sep_cpu_reset_n`` (the
``sep_cpu_reset_n_o`` tb_top probe) and the real ``sep_reset_n_o`` output
(``dbg_sep_reset_n_o``).

Checks (each asserts a specific value, so a stuck/X reset net fails):
  [A]     baseline wdt_rst_ni=1 -> sep_cpu_reset_n == 1 (CPU out of reset) and
          sep_reset_n == 1 (fabric released);
  [B]     wdt_rst_ni=0 -> sep_cpu_reset_n == 0 (CPU held in reset);
  [B-iso] wdt_rst_ni=0 -> sep_reset_n still == 1 (main SEP reset unaffected --
          the gate is CPU-reset-only);
  [C]     wdt_rst_ni=1 -> sep_cpu_reset_n == 1 (CPU reset released again).

The A->B->C toggle is non-vacuous: a tied/stuck sep_cpu_reset_n cannot satisfy
both the ==1 and ==0 checks. Scope is SEP-internal reset-input behavior only; the
WDT-bite -> SMC -> wdt_rst_ni closure is SMC DV scope.

Reg-only / no AXI traffic, so this is a no_cpu run with ``+skip_fuse_sense``.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test

# Cycles to let the combinational reset path settle after a wdt_rst_ni edge.
_SETTLE = 5


@pyuvm.test()
class sep_clock_uvm_wdt_rst_input_reset_path_test(sep_base_test):
    """Drive wdt_rst_ni and verify the sep_cpu_reset_n path + isolation."""

    build_env = False
    required_evidence = ("CHK-BASELINE", "CHK-ASSERT", "CHK-ISOLATION", "CHK-RELEASE")

    async def _check_reset(self, sig, name: str, expected: int, chk_id: str) -> None:
        """Assert a reset observable equals an exact value.

        A compare whose passing branch is 0 reads through ``rd_known`` so an
        unknown bit cannot satisfy it.
        """
        val = self.rd_known(sig) if expected == 0 else self.rd(sig)
        if val != expected:
            raise AssertionError(f"{name}: expected {expected}, got {val}")
        self.logger.info("%s PASS: %s == %d", chk_id, name, expected)

    async def run_scenario(self) -> None:
        dut = cocotb.top

        # Baseline bring-up: wdt_rst_ni defaults to 1 (deasserted), fabric
        # released after fuse-sense-done.
        await self.bring_up_no_cpu()

        # [A] baseline: CPU out of reset, main SEP reset released.
        await self._check_reset(
            dut.sep_cpu_reset_n_o,
            "A baseline wdt_rst_ni=1 -> sep_cpu_reset_n",
            1,
            "CHK-BASELINE",
        )
        await self._check_reset(
            dut.dbg_sep_reset_n_o, "A baseline sep_reset_n released", 1, "CHK-BASELINE"
        )

        # [B] assert the WDT reset input -> CPU held in reset.
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o,
            "B wdt_rst_ni=0 -> sep_cpu_reset_n asserted",
            0,
            "CHK-ASSERT",
        )
        # [B-iso] isolation: the main SEP reset must be unaffected.
        await self._check_reset(
            dut.dbg_sep_reset_n_o,
            "B-iso wdt_rst_ni=0 -> sep_reset_n unaffected",
            1,
            "CHK-ISOLATION",
        )

        # [C] release -> CPU reset deasserts again.
        dut.wdt_rst_ni_i.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o,
            "C wdt_rst_ni=1 -> sep_cpu_reset_n released",
            1,
            "CHK-RELEASE",
        )

        # [D] liveness anchor for the isolation observable. Up to here
        # dbg_sep_reset_n_o has only ever been read expecting 1, so a stuck-high
        # read would have passed [A] and [B-iso] identically. Assert the main reset
        # and require it to read 0, which is the only thing that distinguishes a
        # working observable from a tied-off one.
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.dbg_sep_reset_n_o,
            "D main reset asserted -> sep_reset_n reads",
            0,
            "CHK-ISOLATION",
        )
        dut.rst_ni.value = 1
        await ClockCycles(dut.clk_i, _SETTLE)

        self.logger.info(
            " PASS: wdt_rst_ni -> sep_cpu_reset_n path verified "
            "(A baseline / B assert / B-iso isolation / C release / D isolation "
            "observable proven live)"
        )
