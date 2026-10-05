# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP WDT reset-input path test (PyUVM).

Verifies the SEP WDT reset-input path:

    wdt_rst_ni -> CPU warm reset, system reset isolated

Driving the SEP primary input ``wdt_rst_ni_i`` drops and releases
``sep_cpu_reset_n`` only; it has no fan-out to ``sep_reset_n``. The tb observes
the ``sep_cpu_reset_n_o`` tb_top probe and the real ``sep_reset_n_o`` output
(``dbg_sep_reset_n_o``).

Checks (each asserts an exact value, so a stuck or X reset net fails):
  [A]     wdt_rst_ni=1 -> sep_cpu_reset_n == 1 and sep_reset_n == 1;
  [B]     wdt_rst_ni=0 -> sep_cpu_reset_n == 0;
  [B-iso] sep_reset_n == 1 on every clk_i sample and never changes value
          from the wdt_rst_ni=0 edge to the end of the release settle;
  [C]     wdt_rst_ni=1 -> sep_cpu_reset_n == 1;
  [D]     rst_ni=0 -> sep_reset_n == 0, so the isolation observable is live.

Scope is SEP-internal reset-input behavior; the WDT-bite -> SMC -> wdt_rst_ni loop
is SMC DV scope. No AXI traffic: no_cpu with ``+skip_fuse_sense``.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Edge, First, ReadOnly, RisingEdge
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

        ``rd`` raises on an X/Z bit, so an unknown observable cannot satisfy
        either expectation.
        """
        val = self.rd(sig)
        if val != expected:
            raise AssertionError(f"{name}: expected {expected}, got {val}")
        self.logger.info("%s PASS: %s == %d", chk_id, name, expected)

    async def _watch_held_high(self, sig, clk, state: dict) -> None:
        """Sample ``sig`` on every ``clk`` edge and record any value change.

        ``state["samples"]`` counts the clocked samples. ``state["bad"]`` holds
        the first sample that is not a known 1, and ``state["edges"]`` counts
        value changes of ``sig``, so a pulse shorter than one clock also fails.
        """
        clk_edge = RisingEdge(clk)
        sig_edge = Edge(sig)
        while True:
            fired = await First(clk_edge, sig_edge)
            if fired is sig_edge:
                state["edges"] += 1
            await ReadOnly()
            state["samples"] += 1
            val = sig.value
            if state["bad"] is None and (not val.is_resolvable or int(val) != 1):
                state["bad"] = (state["samples"], str(val))

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

        # [B-iso] watch the main SEP reset across the whole assert/release
        # window, so a drop of any length while the CPU reset is held, or on
        # the release edge, fails.
        iso = {"samples": 0, "edges": 0, "bad": None}
        iso_task = cocotb.start_soon(self._watch_held_high(dut.dbg_sep_reset_n_o, dut.clk_i, iso))

        # [B] assert the WDT reset input -> CPU held in reset.
        dut.wdt_rst_ni_i.value = 0
        await ClockCycles(dut.clk_i, _SETTLE)
        await self._check_reset(
            dut.sep_cpu_reset_n_o,
            "B wdt_rst_ni=0 -> sep_cpu_reset_n asserted",
            0,
            "CHK-ASSERT",
        )
        # [B-iso] isolation: the main SEP reset must be unaffected at the end of
        # the hold window as well as on every clock in it (checked after [C]).
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
        # The kill runs on the last settle edge before the watcher samples it,
        # so the window yields one sample fewer than its 2 * _SETTLE edges.
        iso_task.kill()
        if iso["bad"] is not None or iso["edges"] or iso["samples"] < 2 * _SETTLE - 1:
            raise AssertionError(
                "CHK-ISOLATION FAIL: sep_reset_n did not hold 1 across the wdt_rst_ni "
                f"assert/release window (samples={iso['samples']} "
                f"value_changes={iso['edges']} first_bad={iso['bad']})"
            )
        self.logger.info(
            "CHK-ISOLATION PASS: sep_reset_n == 1 on all %d clk_i samples of the "
            "wdt_rst_ni assert/release window, value_changes=%d",
            iso["samples"],
            iso["edges"],
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
            "PASS: wdt_rst_ni -> sep_cpu_reset_n path verified "
            "(A baseline / B assert / B-iso isolation / C release / D isolation "
            "observable proven live)"
        )
