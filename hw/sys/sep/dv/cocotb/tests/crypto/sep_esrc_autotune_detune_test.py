# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC lane detune: the manual DETUNE mask, the auto-tune toggle and AUTOTUNE_FAIL.

Contract (``hw/ip/entropy_source/doc/architecture.adoc`` Noise Generation;
``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc`` CTRL, INTR_STATUS,
RING_OSC_TUNE):
  * With ``CTRL.AUTOTUNE_ENABLE`` clear the detune of lane i follows
    ``RING_OSC_TUNE.DETUNE`` bit i (architecture.adoc:88-90;
    entropy_source.adoc:368), and a lane failure does not move it.
  * With ``AUTOTUNE_ENABLE`` set the lane detune follows the auto-tune state
    machine, which toggles the lane on a rising edge of a health-test failure
    (architecture.adoc:73, :88-89); a written DETUNE mask is ignored and the
    other lanes do not change.
  * ``INTR_STATUS.AUTOTUNE_FAIL`` sets on a per-generator health-test failure
    while automatic detuning is enabled (entropy_source.adoc:138, :110), and
    stays 0 with it clear. The failing lane latches bit 0 (repetition) of its
    ``GENERATOR_k_HEALTH_STATUS`` (architecture.adoc:126; the stuck lane holds
    a run of W words against ``REPETITION_LIMIT`` = 200, entropy_source.adoc:254).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+esrc_noise_force``. SW_RESET_N baseline 0x20: only the TRNG is released.
The noise model drives ``balanced`` on all 12 lanes from before the TRNG reset
release; a burst is one whole window of stuck1 on lane k with ``balanced`` on the
other lanes. The detune select of each lane is read on ``esrc_detune_o``
(observation tap, ``tb/tb_top.sv``), sampled on every value change.

Randomization (``SepSeededRng`` from the run seed, drawn before the first
stimulus): lane k, the window W (256, 512 or 2048), the three clean gaps (2, 3
or 4 windows), the non-zero masks m1 != m2, the non-zero mask m3 that is not
all ones (its complement m3c is non-zero), and the ``balanced`` masks and
permutation.

Checkers:
  CHK-TUNE-MANUAL   probe == DETUNE readback == written mask for 0, m1, m2; with
                    autotune off no probe bit changes from the off-leg burst start
                    to the end of its gap. Controls: a failure-leg burst toggles
                    probe bit k, and the off-leg burst latches status k bit 0.
  CHK-TUNE-IGNORED  with autotune on and clean noise the probe keeps p0 after
                    DETUNE = m3 and after DETUNE = m3c, and the edge record
                    shows zero probe changes from the p0 sample to the end of
                    the leg (count logged). Control: the leg lasts at least as
                    long as the latest first toggle of bit k after a burst
                    start (CHK-TUNE-TOGGLE), so a tune state machine that
                    toggles with no failure at the failing-noise rate changes
                    the probe in this leg.
  CHK-TUNE-AUTO     after each of three autotune bursts, AUTOTUNE_FAIL = 1 and
                    status k bit 0 = 1; both read 0 before each burst (control).
  CHK-TUNE-TOGGLE   in each autotune burst and its gap probe bit k changes at
                    least once and no other probe bit changes (count logged).
  CHK-TUNE-OFF      after the autotune-off burst status k bit 0 = 1 and
                    AUTOTUNE_FAIL = 0. Control: CHK-TUNE-AUTO sets it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.sep_bit_watch import SepBitWatch
from env.sep_chk_log import SepChkLog
from env.sep_edge_timer import SepEdgeTimer
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Balanced,
    EsrcStrobeTimeout,
    LanePattern,
    SepEsrcPatternNoise,
    Stuck,
    balanced_lanes,
    describe,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from env.sep_trial_wait import TrialTimeout
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_clean_start_seq import SepEsrcCleanStart, SepEsrcLeafSetup

TEST = "sep_esrc_autotune_detune_test"

BASELINE_PARK = ("otbn", "aes", "hmac", "kmac", "abr")
WINDOWS = (256, 512, 2048)
GAPS = (2, 3, 4)
DETUNE_BITS = (1 << NUM_LANES) - 1

REG_POLL_CAP = 4_000  # outer limit of a register poll with no clean time yet (clocks)
PROBE_SETTLE = 4  # clocks between a DETUNE write and the probe sample
PERIOD_STROBES = 8


def _addr(reg: str) -> int:
    return sym(f"ENTROPY_SOURCE_{reg}_REG_ADDR")


def _fmask(reg: str, field: str) -> int:
    return ENTROPY_SOURCE.fields(reg)[field]["bm"]


def _fbp(reg: str, field: str) -> int:
    return ENTROPY_SOURCE.fields(reg)[field]["bp"]


A_CTRL = _addr("CTRL")
A_INTR_STATUS = _addr("INTR_STATUS")
A_INTR_ENABLE = _addr("INTR_ENABLE")
A_RING_OSC_TUNE = _addr("RING_OSC_TUNE")
A_ALERT_THRESHOLD = _addr("ALERT_THRESHOLD")

M_INTR_ALL = ENTROPY_SOURCE.mask("INTR_ENABLE")
M_AUTOTUNE_FAIL = _fmask("INTR_STATUS", "AUTOTUNE_FAIL")
M_DETUNE = _fmask("RING_OSC_TUNE", "DETUNE")
BP_DETUNE = _fbp("RING_OSC_TUNE", "DETUNE")
# Bit 0 of the generator status is the repetition-count failure (architecture.adoc:126).
GEN_REP_BIT = 0x1


def _gen_status_addr(k: int) -> int:
    return _addr(f"GENERATOR_{k}_HEALTH_STATUS")


def _gen_status_mask(k: int) -> int:
    return ENTROPY_SOURCE.mask(f"GENERATOR_{k}_HEALTH_STATUS")


@dataclass(frozen=True)
class Plan:
    seed: int
    lane: int
    window: int
    gaps: tuple[int, int, int]
    m1: int
    m2: int
    m3: int
    balanced: tuple[Balanced, ...]

    @property
    def m3c(self) -> int:
        return ~self.m3 & DETUNE_BITS

    def describe(self) -> str:
        return (
            f"lane={self.lane} window={self.window} gaps={list(self.gaps)} "
            f"m1=0x{self.m1:03x} m2=0x{self.m2:03x} m3=0x{self.m3:03x} m3c=0x{self.m3c:03x} "
            f"{describe(self.balanced)}"
        )


def draw_plan(seed: int) -> Plan:
    """Every draw of the leaf, in a fixed order, with no simulator access."""
    rng = SepSeededRng(seed)
    lane = rng.randrange(NUM_LANES)
    window = rng.choice(WINDOWS)
    gaps = tuple(rng.choice(GAPS) for _ in range(3))
    m1 = 0
    while m1 == 0:
        m1 = rng.getrandbits(NUM_LANES)
    m2 = 0
    while m2 == 0 or m2 == m1:
        m2 = rng.getrandbits(NUM_LANES)
    m3 = 0
    while m3 == 0 or m3 == DETUNE_BITS:
        m3 = rng.getrandbits(NUM_LANES)
    balanced = tuple(balanced_lanes(rng))
    return Plan(seed, lane, window, gaps, m1, m2, m3, balanced)  # type: ignore[arg-type]


class _Esrc(SepAxiRegDriver):
    _DRIVER_TAG = "ESRC"


def _now_ps() -> int:
    return int(get_sim_time("ps"))


@pyuvm.test()
class sep_esrc_autotune_detune_test(sep_base_test):
    """Manual detune, the ignored mask under autotune, the toggle and AUTOTUNE_FAIL."""

    required_evidence = (
        "CHK-TUNE-MANUAL",
        "CHK-TUNE-IGNORED",
        "CHK-TUNE-AUTO",
        "CHK-TUNE-TOGGLE",
        "CHK-TUNE-OFF",
    )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu(park=BASELINE_PARK)
        self.logger.info("BASELINE sw_reset_n=0x%02x", self.swrst.value)

        seed = self.random_seed()
        plan = draw_plan(seed)
        self.plan = plan
        self.logger.info("PLAN seed=%d %s", seed, plan.describe())
        self.chk = SepChkLog(self, TEST, seed)
        self.esrc = _Esrc(self)
        self.clk = SepBitWatch(dut.rst_ni, {"rst_ni": 0}, name="clk_count").start()
        self.noise = SepEsrcPatternNoise(logger=self.logger)
        self.noise.start(plan.balanced)
        self.setup = SepEsrcLeafSetup(self, self.swrst, self.noise)
        self.p = self.setup.period()

        mark = await self._trng_reset()
        cs = SepEsrcCleanStart(
            self,
            self.noise,
            plan.balanced,
            window=plan.window,
            ctrl_fields={"AUTOTUNE_ENABLE": 0},
            extra_writes=(
                (A_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=0)),
            ),
        )
        await cs.run(release_mark=mark)
        self.p = await self.setup.measure_period(self.chk, PERIOD_STROBES)
        await self.setup.wait_boot_done(self.esrc, plan.window)

        self.timer = SepEdgeTimer(dut.esrc_detune_o, name="esrc_detune_o").start()
        # Time from each autotune burst start to the first change of probe bit k.
        self.first_toggle_ps: list[int] = []
        open_graded_window(TEST, self.logger)

        manual = await self._manual_leg()
        off = await self._off_leg()
        ignored = await self._ignored_leg(manual)
        toggles: list[int | None] = []
        for i in range(3):
            toggles.append(await self._auto_burst(i))
        close_graded_window(self.logger)
        await self._clear_status(clear_autotune=True)

        self.chk.obs(
            "TUNE-TOGGLES",
            lane=plan.lane,
            toggles=",".join("na" if t is None else str(t) for t in toggles),
        )
        ctrl_auto_toggle = any(t for t in toggles if t is not None)
        self._grade_manual(manual, off, ctrl_auto_toggle)
        self._grade_off(off, ctrl_auto_fail=self.auto_fail_seen)
        self._grade_ignored(ignored, manual)

        await self.timer.stop()
        await self.noise.stop()
        await self.clk.stop()
        self.chk.finish()

    # --- bus, waits and probes ------------------------------------------------
    def _now(self) -> int:
        return self.clk.clk

    async def _probe(self) -> int:
        await ClockCycles(cocotb.top.clk_i, PROBE_SETTLE)
        return self.rd_known(cocotb.top.esrc_detune_o)

    def _word_bound(self, count: int) -> int:
        # The stimulus word count plus at most one window (never above 2x the
        # count), converted to clocks with the measured strobe period.
        return (count + min(count, self.plan.window)) * self.p + 64

    async def _words(self, count: int, what: str) -> None:
        bound = self._word_bound(count)
        try:
            await self.noise.wait_words(count, bound)
        except EsrcStrobeTimeout as exc:
            raise TrialTimeout(what, bound) from exc

    async def _trng_reset(self) -> int:
        """TRNG bit of SW_RESET_N 0 then 1 (SepEsrcLeafSetup). A timeout raises."""
        mark = await self.setup.trng_reset()
        # Common rule "ESRC interrupt status": the eight defined INTR_ENABLE bits set.
        await self.esrc._wr(A_INTR_ENABLE, M_INTR_ALL)
        return mark

    async def _write_detune(self, mask: int) -> int:
        await self.esrc._wr(A_RING_OSC_TUNE, ENTROPY_SOURCE.value("RING_OSC_TUNE", DETUNE=mask))
        return (await self.esrc._rd(A_RING_OSC_TUNE) & M_DETUNE) >> BP_DETUNE

    async def _write_autotune(self, on: int) -> None:
        await self.esrc._wr(
            A_CTRL, ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1, AUTOTUNE_ENABLE=on)
        )

    async def _reads(self) -> tuple[int, int]:
        """(AUTOTUNE_FAIL, GENERATOR_k_HEALTH_STATUS field bits)."""
        k = self.plan.lane
        intr = await self.esrc._rd(A_INTR_STATUS)
        gen = await self.esrc._rd(_gen_status_addr(k)) & _gen_status_mask(k)
        return int(bool(intr & M_AUTOTUNE_FAIL)), gen

    async def _clear_status(self, *, clear_autotune: bool) -> None:
        k = self.plan.lane
        gen = await self.esrc._rd(_gen_status_addr(k)) & _gen_status_mask(k)
        if gen:
            await self.esrc._wr(_gen_status_addr(k), gen)
        if clear_autotune:
            await self.esrc._wr(A_INTR_STATUS, M_AUTOTUNE_FAIL)

    def _burst_lanes(self) -> list[LanePattern]:
        lanes: list[LanePattern] = list(self.plan.balanced)
        lanes[self.plan.lane] = Stuck(1)
        return lanes

    async def _burst(self, gap: int, what: str) -> tuple[int, int]:
        """One window of stuck1 on lane k, then ``gap`` clean windows.

        Returns the (since_ps, until_ps) of the burst start and the gap end. The
        lane-byte control covers the burst and the gap.
        """
        W = self.plan.window
        c0, m0 = self.noise.byte_control()
        self.noise.byte_check(True)
        t0 = _now_ps()
        self.noise.set_lanes(self._burst_lanes())
        try:
            # The new patterns apply at the next strobe; W strobes later W stuck words ran.
            await self._words(1, f"{what}_start")
            await self._words(W - 1, f"{what}_stuck")
            self.noise.set_lanes(self.plan.balanced)
            await self._words(gap * W + 1, f"{what}_gap")
        finally:
            self.noise.byte_check(False)
            c1, m1 = self.noise.byte_control()
            self.chk.ctrl(
                "NOISE-BYTES",
                m1 - m0 == 0 and c1 - c0 > 0,
                leg=what,
                compared=c1 - c0,
                mismatched=m1 - m0,
            )
        return t0, _now_ps()

    # --- legs --------------------------------------------------------------------
    async def _manual_leg(self) -> dict:
        plan = self.plan
        rows = []
        for mask in (0, plan.m1, plan.m2):
            rb = await self._write_detune(mask)
            probe = await self._probe()
            rows.append((mask, rb, probe))
        return {"rows": rows}

    async def _off_leg(self) -> dict:
        plan = self.plan
        pre_fail, pre_gen = await self._reads()
        self.chk.ctrl(
            "TUNE-OFF",
            pre_fail == 0 and pre_gen == 0,
            pre_autotune_fail=pre_fail,
            pre_gen_status=f"0x{pre_gen:02x}",
        )
        out: dict = {"pre_fail": pre_fail, "pre_gen": pre_gen, "reason": ""}
        try:
            t0, t1 = await self._burst(plan.gaps[0], "off")
        except TrialTimeout as exc:
            out["reason"] = f"timeout:{exc.what} bound={exc.bound}"
            return out
        changes = [c for c in self.timer.since(t0, until_ps=t1) if c.t_ps > t0]
        after = await self._probe()
        fail, gen = await self._reads()
        out.update(changes=len(changes), after=after, fail=fail, gen=gen)
        await self._clear_status(clear_autotune=False)
        return out

    async def _ignored_leg(self, manual: dict) -> dict:
        W = self.plan.window
        out: dict = {"reason": ""}
        await self._write_autotune(1)
        p0 = await self._probe()
        t_p0 = _now_ps()
        probes = []
        try:
            for mask in (self.plan.m3, self.plan.m3c):
                await self._write_detune(mask)
                await self._words(W, "ignored_window")
                probes.append(await self._probe())
        except TrialTimeout as exc:
            out["reason"] = f"timeout:{exc.what} bound={exc.bound}"
        t_end = _now_ps()
        changes = [c for c in self.timer.since(t_p0, until_ps=t_end) if c.t_ps > t_p0]
        out.update(p0=p0, probes=probes, changes=len(changes), span_ps=t_end - t_p0)
        return out

    async def _auto_burst(self, i: int) -> int | None:
        """Burst i+1 of the failure leg. Returns the toggle count of probe bit k."""
        plan = self.plan
        k = plan.lane
        pre_fail, pre_gen = await self._reads()
        self.chk.ctrl(
            "TUNE-AUTO",
            pre_fail == 0 and pre_gen == 0,
            burst=i + 1,
            pre_autotune_fail=pre_fail,
            pre_gen_status=f"0x{pre_gen:02x}",
        )
        try:
            t0, t1 = await self._burst(plan.gaps[i], f"auto{i + 1}")
        except TrialTimeout as exc:
            reason = f"timeout:{exc.what} bound={exc.bound}"
            self.chk.ok("TUNE-TOGGLE", False, lane=k, burst=i + 1, reason=reason)
            self.chk.ok("TUNE-AUTO", False, lane=k, burst=i + 1, reason=reason)
            await self._clear_status(clear_autotune=True)
            return None
        edges = sorted(
            self.timer.rises(t0, until_ps=t1, bit=k) + self.timer.falls(t0, until_ps=t1, bit=k)
        )
        toggles = len(edges)
        if edges:
            self.first_toggle_ps.append(edges[0] - t0)
        moved = [
            j
            for j in range(NUM_LANES)
            if j != k
            and (
                self.timer.rises(t0, until_ps=t1, bit=j) or self.timer.falls(t0, until_ps=t1, bit=j)
            )
        ]
        self.chk.ok(
            "TUNE-TOGGLE",
            toggles >= 1 and not moved,
            lane=k,
            burst=i + 1,
            changes_ge1=toggles >= 1,
            others_unchanged=not moved,
            toggles=toggles,
            moved_lanes=moved or "none",
        )
        fail, gen = await self._reads()
        if fail:
            self.auto_fail_seen = True
        self.chk.ok(
            "TUNE-AUTO",
            fail == 1 and bool(gen & GEN_REP_BIT),
            lane=k,
            burst=i + 1,
            autotune_fail=fail,
            gen_bit0=gen & GEN_REP_BIT,
            gen_status=f"0x{gen:02x}",
        )
        await self._clear_status(clear_autotune=True)
        return toggles

    auto_fail_seen = False

    # --- grading -----------------------------------------------------------------
    def _grade_manual(self, manual: dict, off: dict, ctrl_auto_toggle: bool) -> None:
        plan = self.plan
        rows = manual["rows"]
        follow = all(rb == mask and probe == mask for mask, rb, probe in rows)
        ctrl_off_bit0 = bool(off.get("gen", 0) & GEN_REP_BIT)
        self.chk.ctrl("TUNE-MANUAL", ctrl_auto_toggle, ctrl_auto_toggle=ctrl_auto_toggle)
        self.chk.ctrl("TUNE-MANUAL", ctrl_off_bit0, ctrl_off_gen_bit0=ctrl_off_bit0)
        fields = {
            "detune_reg": ",".join(f"0x{rb:03x}" for _, rb, _ in rows),
            "probe": ",".join(f"0x{p:03x}" for _, _, p in rows),
            "written": ",".join(f"0x{m:03x}" for m, _, _ in rows),
            "after_fail": f"0x{off['after']:03x}" if "after" in off else "na",
            "off_changes": off.get("changes", "na"),
            "ctrl_auto_toggle": ctrl_auto_toggle,
            "ctrl_off_gen_bit0": ctrl_off_bit0,
        }
        if off["reason"]:
            fields["reason"] = off["reason"]
        still = not off["reason"] and off.get("changes") == 0 and off.get("after") == plan.m2
        self.chk.ok("TUNE-MANUAL", follow and still, **fields)

    def _grade_off(self, off: dict, *, ctrl_auto_fail: bool) -> None:
        self.chk.ctrl("TUNE-OFF", ctrl_auto_fail, ctrl_auto_fail=ctrl_auto_fail)
        fields = {
            "lane": self.plan.lane,
            "gen_status": f"0x{off['gen']:02x}" if "gen" in off else "na",
            "autotune_fail": off.get("fail", "na"),
            "ctrl_auto_fail": ctrl_auto_fail,
        }
        if off["reason"]:
            fields["reason"] = off["reason"]
        ok = not off["reason"] and off.get("fail") == 0 and bool(off.get("gen", 0) & GEN_REP_BIT)
        self.chk.ok("TUNE-OFF", ok, **fields)

    def _grade_ignored(self, ign: dict, manual: dict) -> None:
        plan = self.plan
        p0 = ign["p0"]
        probes = ign["probes"]
        changes = ign["changes"]
        span_ps = ign["span_ps"]
        # A healthy failing-noise burst changes bit k within this time; the leg
        # must be at least that long for zero changes to mean anything.
        need_ps = max(self.first_toggle_ps, default=None)
        span_ok = need_ps is not None and span_ps >= need_ps
        self.chk.ctrl(
            "TUNE-IGNORED",
            span_ok,
            span_ps=span_ps,
            first_toggle_ps=self.first_toggle_ps or "na",
        )
        fields = {
            "detune_regs": f"0x{plan.m3:03x},0x{plan.m3c:03x}",
            "p0": f"0x{p0:03x}",
            "probe": ",".join(f"0x{p:03x}" for p in probes) or "na",
            "changes_after_p0": changes,
            "span_ps": span_ps,
            "ctrl_manual_probe": f"0x{manual['rows'][-1][2]:03x}",
        }
        if ign["reason"]:
            fields["reason"] = ign["reason"]
        ok = (
            not ign["reason"] and len(probes) == 2 and all(p == p0 for p in probes) and changes == 0
        )
        self.chk.ok("TUNE-IGNORED", ok, **fields)
