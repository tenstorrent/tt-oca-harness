# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""wdt_rst_ni drops sep_cpu_reset_n; sep_reset_n stays released.

Verifies the SEP WDT reset-input path at the reset outputs:

    wdt_rst_ni -> CPU warm reset, system reset isolated
    wdt_rst_ni -> watchdog reset through the 2-flop capture on clk_i

Contract (``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset Controller):
``sep_cpu_reset_no`` is ``sep_reset_n`` ANDed with ``wdt_rst_ni`` and then the
scan bypass; ``sep_wdt_reset_no`` is ``wdt_rst_ni`` captured by the 2-flop
``u_wdt_rst_sync`` on ``clk_i``. ``test_en_i`` is 0, so both scan bypasses pass
the functional reset. The tb observes the ``sep_cpu_reset_n_o`` tb_top probe,
the real ``sep_reset_n_o`` output (``dbg_sep_reset_n_o``) and the
``sep_wdt_reset_n_probe_o`` tap of ``sep_wdt_reset_n``.

Checks (each asserts an exact value, so a stuck or X reset net fails):
  [A]     wdt_rst_ni=1 -> sep_cpu_reset_n == 1 and sep_reset_n == 1;
  [B]     wdt_rst_ni=0 -> sep_cpu_reset_n == 0;
  [B-iso] sep_reset_n == 1 on every clk_i sample and never changes value
          from the wdt_rst_ni=0 edge to the end of the release settle;
  [C]     wdt_rst_ni=1 -> sep_cpu_reset_n == 1;
  [D]     rst_ni=0 -> sep_reset_n == 0, so the isolation observable is live.
  CHK-WDT-RST-SYNC  ``wdt_rst_ni`` rises on a ``clk_i`` falling edge
          (``CTRL-WDT-RST-OFFEDGE`` logs the measured offset to the nearest
          rising edge; an offset within 1 ps fails the leaf). The
          ``sep_wdt_reset_n`` tap reads 0 before the rise and at the first
          ``clk_i`` rising edge after it, reads 1 at the second, and its rise
          time is that second edge within 1 ps.
  CHK-CPU-RST-AND   on every ``clk_i`` rising edge from the end of bring-up to
          the end of the leaf, ``sep_cpu_reset_n_o`` equals
          ``dbg_sep_reset_n_o`` AND ``wdt_rst_ni_i``, and ``test_en_i`` reads 0.
          Live controls in the same window: the ``wdt_rst_ni`` pulse gives
          samples with only the watchdog term low and the ``rst_ni`` pulse of
          [D] samples with ``sep_reset_n`` low; each count must be non-zero.

Observation: ``OBS-WDT-RD-IN-RST`` logs, for ``WDOG_CTRL``, ``WDOG_COUNT`` and
``INTR_STATE`` read while ``wdt_rst_ni`` is low, the response code, the data
and whether the read timed out (bound: 64 ``clk_wdt_i`` periods per read). The
specification states the reset domains of the register path (``rst_ni``) and
of the AON registers (the watchdog reset), not the result of such a read, so
nothing in it is graded. Before the hold the leaf arms the three registers to
non-reset values with a read-back (``CTRL-WDT-ARM``), so the logged data shows
whether the reset or the armed value comes back. Control: the
``sep_wdt_reset_n`` tap and ``wdt_rst_ni_i`` read 0 after each of those reads
(``CTRL-MISSING`` otherwise).

Environment choices (not from the specification): ``clk_wdt_i`` runs at eight
``clk_i`` periods; the settle of ``_SETTLE`` ``clk_i`` cycles after each
``wdt_rst_ni`` and ``rst_ni`` edge; the 1 ps edge allowance covers the
simulator resolution.

Scope is SEP-internal reset-input behavior; the WDT-bite -> SMC -> wdt_rst_ni loop
is SMC DV scope. Run mode: no_cpu with ``+skip_fuse_sense``; the watchdog
registers are reached over the CPU-LSU AXI master.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, Edge, FallingEdge, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_axi_agent import SepAxiOp
from env.sep_edge_timer import SepEdgeTimer, SepPinEdgeCounter, nearest_edge_offset_ps
from sep_base_test import sep_base_test
from sep_reg_meta import WDT_TIMER
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_wdt_aon_seq import (
    INTR_STATE,
    INTR_TEST,
    INTR_WDOG_BARK,
    WDOG_BARK_THOLD,
    WDOG_BITE_THOLD,
    WDOG_COUNT,
    WDOG_CTRL,
    WDOG_ENABLE,
    SepWdtAon,
)

# Cycles to let the combinational reset path settle after a wdt_rst_ni edge.
_SETTLE = 5
_WDT_RATIO = 8
_EDGE_ALLOWANCE_PS = 1
# Bound of each read while wdt_rst_ni is low, in clk_wdt_i periods.
_RD_IN_RST_BOUND = 64

# Thresholds far above any count the leaf reaches, so the enabled watchdog
# neither barks nor bites on its own.
_BARK = 0x0FFF_0000
_BITE = 0x0FFF_1000
_INTR_BARK_TEST = WDT_TIMER.field_mask("INTR_TEST", "wdog_timer_bark")
_RD_IN_RST = (("WDOG_CTRL", WDOG_CTRL), ("WDOG_COUNT", WDOG_COUNT), ("INTR_STATE", INTR_STATE))


def _now_ps() -> int:
    return int(get_sim_time("ps"))


@pyuvm.test()
class sep_clock_uvm_wdt_rst_input_reset_path_test(sep_base_test):
    """wdt_rst_ni drops and releases sep_cpu_reset_n, and sep_reset_n holds 1 throughout."""

    build_env = True
    required_evidence = (
        "CHK-BASELINE",
        "CHK-ASSERT",
        "CHK-ISOLATION",
        "CHK-RELEASE",
        "CHK-WDT-RST-SYNC",
        "CHK-CPU-RST-AND",
    )

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

    async def _watch_cpu_and(self, state: dict) -> None:
        """Sample the CPU reset and its two AND terms on every ``clk_i`` rising edge.

        ``state["cells"]`` counts the samples per (``sep_reset_n``,
        ``wdt_rst_ni``) pair. ``state["bad"]`` holds the first sample where the
        CPU reset is not the AND of the two terms or ``test_en_i`` is not 0.
        ``rd_known`` raises on an X/Z bit.
        """
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            sep = self.rd_known(dut.dbg_sep_reset_n_o)
            wdt = self.rd_known(dut.wdt_rst_ni_i)
            cpu = self.rd_known(dut.sep_cpu_reset_n_o)
            ten = self.rd_known(dut.test_en_i)
            state["samples"] += 1
            state["cells"][(sep, wdt)] += 1
            if state["bad"] is None and (cpu != (sep & wdt) or ten != 0):
                state["bad"] = (_now_ps(), sep, wdt, cpu, ten)

    async def _tap_ro(self, sig) -> int:
        """``sig`` in the read-only phase of the next ``clk_i`` edge; returns at the falling edge."""
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        val = self.rd_known(sig)
        await FallingEdge(cocotb.top.clk_i)
        return val

    async def _arm(self) -> None:
        """Arm WDOG_CTRL, WDOG_COUNT and INTR_STATE to non-reset values and read them back."""
        await self.wdt.write(WDOG_BARK_THOLD, _BARK)
        await self.wdt.write(WDOG_BITE_THOLD, _BITE)
        await self.wdt.write(WDOG_CTRL, WDOG_ENABLE)
        await self.wdt.write(INTR_TEST, _INTR_BARK_TEST)
        armed = {
            "WDOG_BARK_THOLD": (await self.wdt.read(WDOG_BARK_THOLD), _BARK),
            "WDOG_BITE_THOLD": (await self.wdt.read(WDOG_BITE_THOLD), _BITE),
            "WDOG_CTRL": (await self.wdt.read(WDOG_CTRL) & WDOG_ENABLE, WDOG_ENABLE),
            "INTR_STATE": (await self.wdt.read(INTR_STATE) & INTR_WDOG_BARK, INTR_WDOG_BARK),
        }
        count = await self.wdt.read(WDOG_COUNT)
        line = (
            " ".join(f"{k}=0x{got:x}(want 0x{want:x})" for k, (got, want) in armed.items())
            + f" WDOG_COUNT=0x{count:x}(reset 0x{WDT_TIMER.reset32('WDOG_COUNT'):x})"
        )
        if any(got != want for got, want in armed.values()) or count == WDT_TIMER.reset32(
            "WDOG_COUNT"
        ):
            raise AssertionError(f"CTRL-MISSING WDT-ARM: {line}")
        self.logger.info("CTRL-WDT-ARM: %s", line)

    async def _reads_in_reset(self) -> None:
        """Log each read of the AON registers while wdt_rst_ni is low (not graded)."""
        dut = cocotb.top
        saved = self.cfg.axi_timeout_ns
        bound_ns = _RD_IN_RST_BOUND * self.cfg.wdt_clk_period_ns
        self.cfg.axi_timeout_ns = bound_ns
        try:
            for name, addr in _RD_IN_RST:
                seq = SepAxiAccessSeq(
                    f"wdt_rd_in_rst_{name.lower()}",
                    op=SepAxiOp.READ,
                    addr=addr,
                    length=4,
                    size=2,
                    allow_ungraded_read_resp=True,
                    allow_timeout=True,
                )
                await self.start_seq(seq)
                tap = await self._tap_ro(dut.sep_wdt_reset_n_probe_o)
                wdt_in = self.rd_known(dut.wdt_rst_ni_i)
                if tap != 0 or wdt_in != 0:
                    raise AssertionError(
                        f"CTRL-MISSING WDT-RD-IN-RST: reg={name} sep_wdt_reset_n={tap} "
                        f"wdt_rst_ni={wdt_in}"
                    )
                self.logger.info(
                    "OBS-WDT-RD-IN-RST: reg=%s addr=0x%08x resp=%d data=0x%08x timed_out=%d "
                    "bound_ns=%d sep_wdt_reset_n=%d wdt_rst_ni=%d",
                    name,
                    addr,
                    seq.resp_code,
                    int(seq.rdata) & 0xFFFF_FFFF,
                    int(seq.timed_out),
                    bound_ns,
                    tap,
                    wdt_in,
                )
        finally:
            self.cfg.axi_timeout_ns = saved

    async def _release_wdt_rst(self) -> None:
        """Raise wdt_rst_ni off a clk_i edge and grade its capture (CHK-WDT-RST-SYNC)."""
        dut = cocotb.top
        clk = dut.clk_i
        await FallingEdge(clk)
        dut.wdt_rst_ni_i.value = 1
        t_rise = _now_ps()
        tap_before = self.wdt_t.value_at(t_rise - 1)
        reads = []
        for _ in range(2):
            await RisingEdge(clk)
            t_edge = _now_ps()
            await ReadOnly()
            reads.append((t_edge, self.rd(dut.sep_wdt_reset_n_probe_o, allow_unknown=True)))
        await FallingEdge(clk)
        off = nearest_edge_offset_ps(t_rise, self.edges.edge_times("clk_i"))
        self.logger.info(
            "CTRL-WDT-RST-OFFEDGE: wdt_rst_ni rose t=%d offset_to_clk_edge=%s allowance=%d",
            t_rise,
            off,
            _EDGE_ALLOWANCE_PS,
        )
        if off is None or abs(off) <= _EDGE_ALLOWANCE_PS:
            raise AssertionError(
                f"CTRL-MISSING WDT-RST-OFFEDGE: wdt_rst_ni rose t={t_rise} "
                f"offset_to_clk_edge={off} ps is within {_EDGE_ALLOWANCE_PS} ps of a clk_i edge"
            )
        (t1, v1), (t2, v2) = reads
        rises = self.wdt_t.rises(t_rise)
        t_tap = rises[0] if rises else None
        ok = (
            tap_before == 0
            and v1 == 0
            and v2 == 1
            and t_tap is not None
            and abs(t_tap - t2) <= _EDGE_ALLOWANCE_PS
        )
        values = (
            f"wdt_rst_ni rose t={t_rise} tap_before={tap_before} edge1 t={t1} tap={v1} "
            f"edge2 t={t2} tap={v2} tap_rose t={t_tap} allowance={_EDGE_ALLOWANCE_PS}"
        )
        if not ok:
            raise AssertionError(f"CHK-WDT-RST-SYNC FAIL: {values}")
        self.logger.info("CHK-WDT-RST-SYNC PASS: %s", values)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.cfg.wdt_clk_period_ns = _WDT_RATIO * self.cfg.sys_clk_period_ns
        self.edges = SepPinEdgeCounter(("clk_i",)).start()
        self.wdt_t = SepEdgeTimer(dut.sep_wdt_reset_n_probe_o, name="sep_wdt_reset_n").start()
        self.wdt = SepWdtAon(self)

        # Baseline bring-up: wdt_rst_ni defaults to 1 (deasserted), fabric
        # released after fuse-sense-done.
        await self.bring_up_no_cpu()
        self.logger.info(
            "CFG clk_i=%.3f ns clk_wdt_i=%.3f ns (ratio %d) rd_in_rst_bound=%d clk_wdt_i periods",
            self.cfg.sys_clk_period_ns,
            self.cfg.wdt_clk_period_ns,
            _WDT_RATIO,
            _RD_IN_RST_BOUND,
        )

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

        cpu_and = {"samples": 0, "cells": {(s, w): 0 for s in (0, 1) for w in (0, 1)}, "bad": None}
        and_task = cocotb.start_soon(self._watch_cpu_and(cpu_and))

        await self._arm()

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

        await self._reads_in_reset()

        # [C] release off a clk_i edge -> the watchdog reset releases on the
        # second clk_i edge and the CPU reset deasserts again.
        await self._release_wdt_rst()
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

        and_task.kill()
        cells = cpu_and["cells"]
        cell_str = " ".join(f"sep{s}_wdt{w}={n}" for (s, w), n in sorted(cells.items()))
        live = cells[(1, 0)] > 0 and cells[(0, 1)] > 0 and cells[(1, 1)] > 0
        if cpu_and["bad"] is not None or not live:
            raise AssertionError(
                f"CHK-CPU-RST-AND FAIL: samples={cpu_and['samples']} {cell_str} "
                f"first_bad(t,sep,wdt,cpu,test_en)={cpu_and['bad']}"
            )
        self.logger.info(
            "CHK-CPU-RST-AND PASS: sep_cpu_reset_n == sep_reset_n & wdt_rst_ni, test_en=0 "
            "on all %d clk_i samples: %s",
            cpu_and["samples"],
            cell_str,
        )
        await self.wdt_t.stop()
        await self.edges.stop()

        self.logger.info(
            "PASS: wdt_rst_ni -> sep_cpu_reset_n path verified "
            "(A baseline / B assert / B-iso isolation / C release / D isolation "
            "observable proven live / watchdog reset capture / CPU reset AND)"
        )
