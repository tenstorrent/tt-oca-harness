# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_ref_reset_cycles_test.

Spec: clk_rst.adoc (Power-Good and Cold Reset), port_table.adoc (SMC Port Declaration).

``rst_cold_ni`` is conditioned in the ``clk_ref_i`` domain: assertion needs 32 consecutive low
samples and the release is extended by 255 cycles. The sequence counts ``clk_ref_i`` rising
edges from the pin release to ``rst_primary_ref_clk_no`` reading 1, and from a pin drive low to
the output reading 0, so the counts are cycle counts at any reference period.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

COLD_LOW_SAMPLES = 64
RELEASE_MIN_CYCLES = 255
GLITCH_SAMPLES = 31
ASSERT_SAMPLES = 32
IGNORE_WINDOW_SAMPLES = 100
BOUND_REF_CYCLES = 600
_EDGE_HISTORY = 1024
FENCE = (
    "BRINGUP_DONE",
    "COLD_LOW_64",
    "RELEASE_COUNTED",
    "GLITCH_31_IGNORED",
    "PULSE_32_ASSERTED",
    "CHAIN_RELEASED",
)
CHECKERS = ("CHK-REF-RESET-RELEASE-CYCLES", "CHK-REF-RESET-DEGLITCH")


def _now_ps() -> int:
    return int(round(get_sim_time("ps")))


class _EdgeLog:
    """Rising-edge timestamps (ps) of one clock, kept in a bounded list."""

    def __init__(self) -> None:
        self.times: list[int] = []

    async def run(self, clk) -> None:
        while True:
            await RisingEdge(clk)
            self.times.append(_now_ps())
            if len(self.times) > _EDGE_HISTORY:
                del self.times[: len(self.times) - _EDGE_HISTORY]

    def edges_in(self, lo_ps: int, hi_ps: int) -> int:
        """Rising edges with ``lo < t <= hi``."""
        return sum(1 for t in self.times if lo_ps < t <= hi_ps)


class smc_ref_reset_cycles_test_seq(SmcResetSeqBase):
    """Release hold and assertion de-glitch of the cold reset, in clk_ref_i cycles."""

    RELEASE_BOUND_REF_CYCLES = BOUND_REF_CYCLES

    def __init__(self, name: str = "smc_ref_reset_cycles_test_seq") -> None:
        super().__init__(name)
        self.n_rel: int | None = None
        self.n_assert: int | None = None
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []

    def _stamp(self, term: str) -> None:
        self._stamps.append((term, _now_ps()))
        cocotb.log.info("STEP %s", term)

    def _log_chk(self, chk_id: str, text: str) -> None:
        self._chk_marks.append((chk_id, _now_ps()))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _level(sig, what: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{what} is not resolvable: {value}"
        return int(value)

    async def _drive_low(self, op, third_ps: int) -> int:
        """Move to a point a third of a period after a clk_ref_i edge, drive; return the time."""
        await RisingEdge(cocotb.top.clk_ref_i)
        await Timer(third_ps, unit="ps")
        t_ps = _now_ps()
        await self._send(op)
        return t_ps

    async def _chain_released(self, name: str) -> None:
        item = await self._wait_released(name, bound=BOUND_REF_CYCLES)
        self._waits.append(
            f"{name}={BOUND_REF_CYCLES} last={item.rst_primary_ref_clk_n}@{item.wait_ref_cycles}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "rst_primary_ref_clk_no"), "rst_primary_ref_clk_no probe is missing"
        ref_log = _EdgeLog()
        task = cocotb.start_soon(ref_log.run(dut.clk_ref_i))
        try:
            await self._scenario(dut, ref_log)
        finally:
            task.cancel()

    async def _scenario(self, dut, ref_log: _EdgeLog) -> None:
        out = dut.rst_primary_ref_clk_no
        third_ps = int(round(self.cfg.ref_clk_period_ns * 1000)) // 3

        # S1 -- bring-up done by smc_base_test.
        s1 = await self._send(SmcResetOp.SAMPLE)
        assert s1.resolvable and s1.rst_primary_ref_clk_n == 1, s1
        self._stamp("BRINGUP_DONE")

        # S2 -- 64 clk_ref_i cycles low, then count from the release to the output reading 1.
        t_low = await self._drive_low(SmcResetOp.COLD_RST_LO, third_ps)
        for _ in range(COLD_LOW_SAMPLES):
            await RisingEdge(dut.clk_ref_i)
        await Timer(third_ps, unit="ps")
        t_high = _now_ps()
        low_level = self._level(out, "rst_primary_ref_clk_no")
        await self._send(SmcResetOp.COLD_RST_HI)
        low_edges = ref_log.edges_in(t_low, t_high)
        assert low_edges == COLD_LOW_SAMPLES, (
            f"rst_cold_ni low spanned {low_edges} clk_ref_i edges, expected {COLD_LOW_SAMPLES}"
        )
        assert low_level == 0, f"rst_primary_ref_clk_no reads {low_level} after the 64-cycle low"
        self._stamp("COLD_LOW_64")

        n_rel = None
        level = low_level
        for n in range(1, BOUND_REF_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            level = self._level(out, "rst_primary_ref_clk_no")
            if level == 1:
                n_rel = n
                break
        assert n_rel is not None, (
            f"rst_primary_ref_clk_no still {level} {BOUND_REF_CYCLES} clk_ref_i cycles after "
            f"the release"
        )
        self._waits.append(f"release_count={BOUND_REF_CYCLES} last={level}@{n_rel}")
        assert n_rel >= RELEASE_MIN_CYCLES, (
            f"release-to-high count {n_rel} clk_ref_i cycles is below {RELEASE_MIN_CYCLES}"
        )
        self.n_rel = n_rel
        self._stamp("RELEASE_COUNTED")
        await self._chain_released("chain_release_after_64")
        still = self._level(out, "rst_primary_ref_clk_no")
        assert still == 1, f"rst_primary_ref_clk_no reads {still} after the chain release wait"
        self._log_chk(
            "CHK-REF-RESET-RELEASE-CYCLES",
            f"N_rel={n_rel} clk_ref_i cycles from the rst_cold_ni release to "
            f"rst_primary_ref_clk_no=1 at ref {self.cfg.ref_clk_period_ns} ns "
            f"(minimum {RELEASE_MIN_CYCLES}; owner value pending); "
            f"rst_primary_ref_clk_no reads {still} after the chain release",
        )

        # S3 -- a 31-cycle pulse is ignored.
        t_low = await self._drive_low(SmcResetOp.COLD_RST_LO, third_ps)
        samples = 0
        for _ in range(GLITCH_SAMPLES):
            await RisingEdge(dut.clk_ref_i)
            assert self._level(out, "rst_primary_ref_clk_no") == 1, (
                f"rst_primary_ref_clk_no fell inside the {GLITCH_SAMPLES}-cycle pulse"
            )
            samples += 1
        await Timer(third_ps, unit="ps")
        t_high = _now_ps()
        await self._send(SmcResetOp.COLD_RST_HI)
        measured = ref_log.edges_in(t_low, t_high)
        assert measured == GLITCH_SAMPLES, (
            f"glitch pulse spanned {measured} clk_ref_i edges, expected {GLITCH_SAMPLES}"
        )
        for _ in range(IGNORE_WINDOW_SAMPLES):
            await RisingEdge(dut.clk_ref_i)
            assert self._level(out, "rst_primary_ref_clk_no") == 1, (
                f"rst_primary_ref_clk_no fell after the {GLITCH_SAMPLES}-cycle pulse"
            )
            samples += 1
        self._waits.append(f"glitch_hold={samples} last=1")
        self._stamp("GLITCH_31_IGNORED")
        glitch_samples = samples

        # S3 -- a 32-cycle pulse asserts the output.
        t_low = await self._drive_low(SmcResetOp.COLD_RST_LO, third_ps)
        t_high = None
        n_assert = None
        level = 1
        for n in range(1, BOUND_REF_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            level = self._level(out, "rst_primary_ref_clk_no")
            if n == ASSERT_SAMPLES:
                await Timer(third_ps, unit="ps")
                t_high = _now_ps()
                await self._send(SmcResetOp.COLD_RST_HI)
            if level == 0:
                n_assert = n
                break
        assert n_assert is not None, (
            f"rst_primary_ref_clk_no still {level} {BOUND_REF_CYCLES} clk_ref_i cycles after "
            f"the {ASSERT_SAMPLES}-cycle pulse started"
        )
        if t_high is None:
            t_high = _now_ps()
            await self._send(SmcResetOp.COLD_RST_HI)
        measured = ref_log.edges_in(t_low, t_high)
        assert measured >= min(n_assert, ASSERT_SAMPLES), (measured, n_assert)
        self._waits.append(f"assert_count={BOUND_REF_CYCLES} last={level}@{n_assert}")
        self.n_assert = n_assert
        self._stamp("PULSE_32_ASSERTED")
        self._log_chk(
            "CHK-REF-RESET-DEGLITCH",
            f"a {GLITCH_SAMPLES}-cycle low pulse left rst_primary_ref_clk_no high at all "
            f"{glitch_samples} samples; a {ASSERT_SAMPLES}-cycle low pulse drove it to 0 "
            f"{n_assert} clk_ref_i cycles after the first low sample "
            f"at ref {self.cfg.ref_clk_period_ns} ns (owner value pending)",
        )
        await self._chain_released("chain_release_after_32")
        self._stamp("CHAIN_RELEASED")
        self._finish_fence()

    def _finish_fence(self) -> None:
        ids = [s for s, _ in self._stamps]
        assert ids == list(FENCE), f"fence order {ids}, expected {list(FENCE)}"
        stamps = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chk_ids = [c for c, _ in self._chk_marks]
        assert chk_ids == list(CHECKERS), f"checker order {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk, t_chk), term in zip(self._chk_marks, ("RELEASE_COUNTED", "PULSE_32_ASSERTED")):
            assert t_chk >= stamp_of[term], f"{chk} printed at {t_chk} before {term}"
        chk_times = [t for _, t in self._chk_marks]
        assert chk_times[0] < chk_times[1], f"checker lines out of order {chk_times}"
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(self._waits),
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE),
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
