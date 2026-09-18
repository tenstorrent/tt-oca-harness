# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset assertion is asynchronous, deassertion synchronous, through multiple stages.

``clk_rst.adoc`` (Reset Synchronization and Timing Integrity) states that the
synchronized resets use ``prim_rst_sync`` primitives in the target clock
domain, that "reset assertion is asynchronous and deassertion is synchronous",
and that the primitives "include multiple flip-flop stages". The Reference
Clock Domain section adds that the reference domain "serves as the
synchronization anchor for reset domain crossings". Those four sentences are
turned into timestamp relations on the two primary reset outputs, sampled at
simulation-time resolution:

* assertion: ``rst_primary_smc_clk_no`` and ``rst_primary_ref_clk_no`` fall in
  the same simulation instant, and that instant is a ``clk_ref_i`` rising edge
  (the anchor). A synchronous assertion in the SMC domain would have waited
  for the next ``clk_smc_i`` edge and could not coincide with the reference
  domain's output.
* deassertion: each output rises exactly at a rising edge of its own target
  clock, and the SMC output rises an integer number of ``clk_smc_i`` edges
  after the reference-domain anchor of the release.
* stages: at least two target-clock edges separate the release anchor from
  each output's rise. The anchor is the first ``clk_ref_i`` rising edge after
  the pin is released, which is when the de-glitcher's shift register first
  samples the released pin; the specification pins no stage count, so only
  "more than one" is asserted and the measured count is reported.

The cool reset pin is used as the source because its de-glitch path has no
release extender; the pin is driven at a phase one third into a clock period
so that none of the coincidences below can be an artefact of the stimulus
landing on an edge.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge, Timer, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

try:
    from cocotb.result import SimTimeoutError
except ImportError:  # cocotb 2.x
    from cocotb.triggers import SimTimeoutError

# The cool de-glitcher needs the pin held asserted for 32 clk_ref_i samples
# before rst_primary_no follows; 200 is the same ceiling smc_cold_reset_test
# uses for its assert handshake. Expiry is a failure.
ASSERT_BOUND_REF_CYCLES = 200
RELEASE_BOUND_REF_CYCLES = 200
# clk_ref_i rising edges the pin is held low so the de-glitcher is guaranteed
# to have seen 32 consecutive asserted samples before release.
HOLD_ASSERTED_REF_CYCLES = 64
# Recent rising-edge timestamps kept per clock (long enough to span the
# release window at the slowest ratio).
_EDGE_HISTORY = 512
# clk_rst.adoc: "multiple flip-flop stages" -- more than one.
MIN_SYNC_STAGES = 2


def _now_ps() -> int:
    return int(round(get_sim_time("ps")))


class _EdgeLog:
    """Rising-edge timestamps (ps) of one clock, kept in a bounded list."""

    def __init__(self, name: str) -> None:
        self.name = name
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

    def first_after(self, t_ps: int) -> int:
        later = [t for t in self.times if t > t_ps]
        assert later, f"{self.name}: no rising edge recorded after {t_ps} ps"
        return min(later)


class smc_reset_sync_edge_test_seq(SmcResetSeqBase):
    """Cool-pin assert/release with sub-cycle observation of the synced outputs."""

    def __init__(self, name: str = "smc_reset_sync_edge_test_seq") -> None:
        super().__init__(name)
        self.t_pin_low: int | None = None
        self.t_fall_ref: int | None = None
        self.t_fall_smc: int | None = None
        self.smc_edge_at_fall: bool | None = None
        self.t_pin_high: int | None = None
        self.t_anchor: int | None = None
        self.t_rise_ref: int | None = None
        self.t_rise_smc: int | None = None
        self.stages_ref: int | None = None
        self.stages_smc: int | None = None

    async def _fall_edges(self, dut, ref_log: _EdgeLog, smc_log: _EdgeLog) -> None:
        """Wait for the reference-domain output to assert, then inspect the same instant."""
        bound_ns = ASSERT_BOUND_REF_CYCLES * self.cfg.ref_clk_period_ns
        try:
            await with_timeout(FallingEdge(dut.rst_primary_ref_clk_no), bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"rst_primary_ref_clk_no did not assert within {bound_ns} ns of rst_cool_ni=0"
            ) from exc
        self.t_fall_ref = _now_ps()
        await ReadOnly()
        smc_now = int(dut.rst_primary_smc_clk_no.value)
        assert smc_now == 0, (
            f"rst_primary_smc_clk_no still {smc_now} at {self.t_fall_ref} ps, the instant "
            f"rst_primary_ref_clk_no asserted: the SMC-domain assertion waited for its own "
            f"clock instead of propagating asynchronously"
        )
        self.t_fall_smc = self.t_fall_ref
        assert ref_log.times and ref_log.times[-1] == self.t_fall_ref, (
            f"assertion instant {self.t_fall_ref} ps is not a clk_ref_i rising edge (last edge "
            f"{ref_log.times[-1] if ref_log.times else None} ps); the reset crossing is not "
            f"anchored on the reference clock"
        )
        self.smc_edge_at_fall = bool(smc_log.times) and smc_log.times[-1] == self.t_fall_ref
        await Timer(1, unit="ps")

    async def _rise_edge(self, dut, signal, log: _EdgeLog, label: str) -> tuple[int, int]:
        """Wait for one output to release; return (rise time, matching clock-edge time)."""
        bound_ns = RELEASE_BOUND_REF_CYCLES * self.cfg.ref_clk_period_ns
        try:
            await with_timeout(RisingEdge(signal), bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label} did not release within {bound_ns} ns of rst_cool_ni=1"
            ) from exc
        t_rise = _now_ps()
        await ReadOnly()
        assert log.times and log.times[-1] == t_rise, (
            f"{label} released at {t_rise} ps, which is not a {log.name} rising edge (last edge "
            f"{log.times[-1] if log.times else None} ps): deassertion is not synchronous to the "
            f"target clock"
        )
        await Timer(1, unit="ps")
        return t_rise, log.times[-1]

    async def body(self) -> None:
        dut = cocotb.top
        ref_log = _EdgeLog("clk_ref_i")
        smc_log = _EdgeLog("clk_smc_i")
        ref_task = cocotb.start_soon(ref_log.run(dut.clk_ref_i))
        smc_task = cocotb.start_soon(smc_log.run(dut.clk_smc_i))
        ref_ps = self.cfg.ref_clk_period_ns * 1000
        smc_ps = self.cfg.smc_clk_period_ns * 1000
        try:
            # Entry state: every reset observable released (scoreboard verdict).
            await self._send(SmcResetOp.SAMPLE)

            # --- assertion, driven one third into a clk_smc_i period --------------
            await RisingEdge(dut.clk_smc_i)
            await Timer(smc_ps // 3, unit="ps")
            self.t_pin_low = _now_ps()
            dut.rst_cool_ni.value = 0
            await self._fall_edges(dut, ref_log, smc_log)
            await self._wait_state(
                "COOL_ASSERTED",
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=1,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
            )
            for _ in range(HOLD_ASSERTED_REF_CYCLES):
                await RisingEdge(dut.clk_ref_i)

            # --- release, driven one third into a clk_ref_i period ------------------
            await RisingEdge(dut.clk_ref_i)
            await Timer(ref_ps // 3, unit="ps")
            self.t_pin_high = _now_ps()
            dut.rst_cool_ni.value = 1

            ref_wait = cocotb.start_soon(
                self._rise_edge(dut, dut.rst_primary_ref_clk_no, ref_log, "rst_primary_ref_clk_no")
            )
            smc_wait = cocotb.start_soon(
                self._rise_edge(dut, dut.rst_primary_smc_clk_no, smc_log, "rst_primary_smc_clk_no")
            )
            self.t_rise_ref, _ = await ref_wait
            self.t_rise_smc, _ = await smc_wait
            await self._wait_released("COOL_RELEASED")
        finally:
            ref_task.cancel()
            smc_task.cancel()

        # The release anchor: the first clk_ref_i rising edge after the pin was
        # released is when the de-glitcher first samples a released pin.
        self.t_anchor = ref_log.first_after(self.t_pin_high)
        assert (self.t_rise_ref - self.t_anchor) % ref_ps == 0, (
            f"rst_primary_ref_clk_no rose {self.t_rise_ref - self.t_anchor} ps after the "
            f"clk_ref_i anchor, not a whole number of clk_ref_i periods ({ref_ps} ps)"
        )
        self.stages_ref = ref_log.edges_in(self.t_anchor, self.t_rise_ref)
        self.stages_smc = smc_log.edges_in(self.t_anchor, self.t_rise_smc)
        assert self.stages_ref >= MIN_SYNC_STAGES, (
            f"rst_primary_ref_clk_no released only {self.stages_ref} clk_ref_i edge(s) after the "
            f"release anchor: not a multi-stage synchronizer"
        )
        assert self.stages_smc >= MIN_SYNC_STAGES, (
            f"rst_primary_smc_clk_no released only {self.stages_smc} clk_smc_i edge(s) after the "
            f"release anchor: not a multi-stage synchronizer"
        )
        assert self.t_rise_smc > self.t_anchor and self.t_rise_ref > self.t_anchor

        cocotb.log.info(
            "CHK-RESET-SYNC-ASYNC-ASSERT: rst_cool_ni=0 at %d ps (clk_smc_i phase %d/%d ps); "
            "rst_primary_ref_clk_no and rst_primary_smc_clk_no both asserted at %d ps, a clk_ref_i "
            "rising edge; a clk_smc_i rising edge %s at that instant, so the SMC-domain output "
            "asserted without waiting for its own clock",
            self.t_pin_low,
            smc_ps // 3,
            smc_ps,
            self.t_fall_ref,
            "coincided" if self.smc_edge_at_fall else "did not occur",
        )
        cocotb.log.info(
            "CHK-RESET-SYNC-SYNC-DEASSERT: rst_cool_ni=1 at %d ps (clk_ref_i phase %d/%d ps); "
            "release anchor (first clk_ref_i edge after the pin) %d ps; rst_primary_ref_clk_no rose "
            "at %d ps on a clk_ref_i edge, rst_primary_smc_clk_no rose at %d ps on a clk_smc_i edge",
            self.t_pin_high,
            ref_ps // 3,
            ref_ps,
            self.t_anchor,
            self.t_rise_ref,
            self.t_rise_smc,
        )
        cocotb.log.info(
            "CHK-RESET-SYNC-MULTI-STAGE: %d clk_ref_i edges (ref domain) and %d clk_smc_i edges "
            "(SMC domain) separate the release anchor from each output's rise; both >= %d",
            self.stages_ref,
            self.stages_smc,
            MIN_SYNC_STAGES,
        )
        cocotb.log.info(
            "CHK-RESET-SYNC-REF-ANCHOR: assertion instant %d ps and release anchor %d ps are both "
            "clk_ref_i rising edges (ref period %d ps, smc period %d ps)",
            self.t_fall_ref,
            self.t_anchor,
            ref_ps,
            smc_ps,
        )
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: %s", line)
