# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_AXICLK_CG_TEST ANCHOR: smc_zeroer_axiclk_cg_test

DV-CARD: SMC_CG_P2_002 ANCHOR: smc_zeroer_axiclk_cg_test

The P2 card extends this same anchor (additive): the P1 steps/checkers above are
UNCHANGED (their evidence tokens must keep appearing verbatim for the closed P1
grade); the P2 extension below (_p2_extension) adds the busy-to-idle
back-to-back trigger race, called once at the end of body(). Per SF-005
(answered): trigger at same-cycle/after the busy falling edge MUST start and
complete the follow-on op (scored); trigger while still busy (1-cycle-before,
genuine overlap) is evidence-only -- no pass/fail asserted on that protocol
outcome. That carve-out applies ONLY to CHK-ZEROER-AXICLK-COMPLETION's
protocol-outcome verdict.

AMENDMENT (revision 2, supersedes revision 1, owner decision minshaoho
standing order "approve-and-continue" amend choice (ii), approved 2026-08-05T17:25:00+08:00):
revision 1's CHK-ZEROER-AXICLK-NOGLITCH required zero axi_clk_enable deassert
across the WHOLE busy-to-idle boundary, including the real ~26-28 clk_smc_i
cycle turnaround of the documented 3-write DEST_ADDR->SIZE->CTRL_STATUS
trigger protocol -- physically unreachable via that frontdoor protocol at all
3 swept timings (see revision-1 (B) finding, kept log run 20260805_091625,
now STALE against this revision). Revision 2 narrows the proof: while
zeroer_busy_o==1 for EITHER operation (op1's tail or op2's own busy span),
axi_clk_enable must stay asserted with zero deassert -- no mid-busy glitch --
at all 3 swept timings (still scored, still no carve-out for this half of the
checker). A deassert gap occurring STRICTLY BETWEEN the two busy pulses
(caused by the multi-write trigger protocol's turnaround latency) is now
PERMITTED and must be LOGGED (start cycle, end cycle, duration) at each swept
timing -- never scored as a failure. CHK-ZEROER-AXICLK-COMPLETION is
unchanged (same-cycle/1-after scored; 1-before evidence-only per SF-005).
`_p2_race_cell` below implements this split by classifying every deasserted
(enable==0) sample as either "mid-busy" (busy==1 at that sample -- fail_on
scope) or "inter-busy gap" (busy==0, strictly between op1's busy-fall and
op2's busy-reassert -- logged, not scored), never by which swept timing is
under test.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

_LOG = logging.getLogger(__name__)

HYST = 8
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 256
ZEROER_WAIT_CYCLES = 200

# Authoritative map (also re-exported via smc_cg_obs_utils).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK
INBOUND0_FILTER_CONFIG = _addr.INBOUND0_FILTER_CONFIG
INBOUND0_START = _addr.INBOUND0_START
INBOUND0_END = _addr.INBOUND0_END
OUTBOUND0_FILTER_CONFIG = _addr.OUTBOUND0_FILTER_CONFIG
OUTBOUND0_START = _addr.OUTBOUND0_START
OUTBOUND0_END = _addr.OUTBOUND0_END
PASS_ALL_CONFIG = cg.PASS_ALL_CONFIG
ZEROER_CTRL_DEST_ADDR = _addr.ZEROER_CTRL_DEST_ADDR
ZEROER_CTRL_SIZE = _addr.ZEROER_CTRL_SIZE
ZEROER_CTRL_STATUS = _addr.ZEROER_CTRL_STATUS

OUTPUT_FABRIC_ADDR = 0x0200_0000
OUTPUT_FABRIC_MODEL_REGION = "zeroer_axi_cg_fabric"
OUTPUT_FABRIC_MODEL_SIZE = 0x1000
ZEROER_POISON = bytes.fromhex("a0a1a2a3a4a5a6a7")

# P2 (SMC_CG_P2_002) additions: back-to-back trigger race vs the axi_clk
# busy-to-idle boundary. Single-beat (8B) ops keep op1's own busy duration
# small and repeatable so the 3 required relative timings can be scheduled
# against the DUT's own observed busy_hold (never a hand literal).
P2_OP_SIZE = 8
P2_DEST_CALIB = OUTPUT_FABRIC_ADDR + 0x100
P2_DEST_OP1 = OUTPUT_FABRIC_ADDR + 0x200
P2_DEST_OP2 = OUTPUT_FABRIC_ADDR + 0x300
P2_CALIB_TIMEOUT_SMC = 300
P2_TRIAL_TIMEOUT_SMC = 400
P2_FOLLOWON_BOUND_SMC = 300
# (label, offset relative to op1's busy-falling edge: -1/0/+1 cycle)
P2_CELLS = (
    ("1-cycle-before-busy-deassert", -1),
    ("same-cycle-as-busy-deassert", 0),
    ("1-cycle-after-busy-deassert", 1),
)


class smc_zeroer_axiclk_cg_test_seq(SmcCsrSeq):
    """LIVE Zeroer axi_clk gating (idle / busy / disable_cg / reset override)."""

    def __init__(self, name: str = "smc_zeroer_axiclk_cg_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(self, *, zeroer_en: bool, hyst: int = HYST) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~ZEROER_CG_EN & ~CG_HYST_MASK) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert (rb & ZEROER_CG_EN) == (ZEROER_CG_EN if zeroer_en else 0)

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL",
            INBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL",
            OUTBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        assert self.env is not None
        item_name = f"jtag_zaxi_wr_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        item.update_golden = True
        item.memory_region = OUTPUT_FABRIC_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    def _write_count(self) -> int:
        sig = self._dut().tb_output_axi_write_count
        assert sig.value.is_resolvable
        return int(sig.value)

    async def _wait_zeroer_idle(self) -> None:
        dut = self._dut()
        for _ in range(ZEROER_WAIT_CYCLES):
            if cg.sample_bit(dut, "tb_zeroer_busy") == 0:
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError("TIMEOUT waiting zeroer_busy_o clear")

    async def _trigger_zeroer(self) -> None:
        await self.csr_write(
            "ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, OUTPUT_FABRIC_ADDR, length=8
        )
        await self.csr_write("ZEROER_SIZE", ZEROER_CTRL_SIZE, len(ZEROER_POISON), length=8)
        await self.csr_write("ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)

    async def _measure_busy_window_toggles(self) -> tuple[int, int, int]:
        """Resume delta + every-cycle enable count from resume through busy clear.

        Card allows resume within one cycle of busy assert; every-cycle proof
        starts at the resume sample (not the pre-resume busy cycle).
        """
        dut = self._dut()
        state = {
            "busy_at": -1,
            "resume_at": -1,
            "post_resume_cycles": 0,
            "enabled_hits": 0,
            "smc": 0,
            "done": False,
        }

        async def _mon() -> None:
            while not state["done"] and state["smc"] < BUSY_TIMEOUT_SMC * 8:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                await ReadOnly()
                busy = cg.sample_bit(dut, "tb_zeroer_busy") == 1
                gval = dut.tb_zeroer_gated_axi_clk.value
                if gval.is_resolvable is False:
                    raise AssertionError("tb_zeroer_gated_axi_clk sample is X/Z")
                gated_on = int(gval) == 1
                await Timer(1, unit="ps")
                if state["busy_at"] < 0 and busy:
                    state["busy_at"] = state["smc"]
                if state["busy_at"] >= 0 and state["resume_at"] < 0 and gated_on:
                    state["resume_at"] = state["smc"]
                if state["resume_at"] >= 0 and busy:
                    state["post_resume_cycles"] += 1
                    if gated_on:
                        state["enabled_hits"] += 1
                elif state["busy_at"] >= 0 and not busy:
                    state["done"] = True
                    return

        mon = cocotb.start_soon(_mon())
        await self._trigger_zeroer()
        for _ in range(BUSY_TIMEOUT_SMC * 8):
            if state["done"]:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.cancel()
        assert state["busy_at"] >= 0, "zeroer_busy never asserted"
        assert state["resume_at"] >= 0, "axi_clk did not resume"
        assert state["done"], "TIMEOUT waiting busy clear during toggle monitor"
        delta = max(0, state["resume_at"] - state["busy_at"])
        return delta, state["enabled_hits"], state["post_resume_cycles"]

    # ---- P2 (SMC_CG_P2_002) helpers -----------------------------------

    async def _p2_sample_cycle(self) -> tuple[int, int]:
        """One clk_smc_i period; returns (busy, axi_clk_enabled) sampled at
        ReadOnly, same technique as `_measure_busy_window_toggles`."""
        dut = self._dut()
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        busy = cg.sample_bit(dut, "tb_zeroer_busy")
        gval = dut.tb_zeroer_gated_axi_clk.value
        if gval.is_resolvable is False:
            raise AssertionError("tb_zeroer_gated_axi_clk sample is X/Z")
        enabled = int(gval)
        await Timer(1, unit="ps")
        return busy, enabled

    async def _p2_trigger_op(self, dest_addr: int, size: int) -> None:
        await self.csr_write("P2_ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, dest_addr, length=8)
        await self.csr_write("P2_ZEROER_SIZE", ZEROER_CTRL_SIZE, size, length=8)
        await self.csr_write("P2_ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, 0x1, length=8)

    async def _p2_measure_busy_hold(self) -> int:
        """Calibration only (NOT a scored SMC-CG-ZEROER-AXICLK.S1 cell):
        trigger a solo op1-shaped operation from idle and measure the exact
        clk_smc_i cycle span busy stays asserted, so the 3 required race
        timings can be scheduled against the DUT's own observed timing
        (CHK-NO-TAUTOLOGY: never a hand literal)."""
        await self._wait_zeroer_idle()
        timeline: list[int] = []
        task = cocotb.start_soon(self._p2_trigger_op(P2_DEST_CALIB, P2_OP_SIZE))
        while not task.done():
            busy, _en = await self._p2_sample_cycle()
            timeline.append(busy)
        start_idx = next((i for i, b in enumerate(timeline) if b == 1), None)
        fall_idx = None
        for _ in range(P2_CALIB_TIMEOUT_SMC):
            busy, _en = await self._p2_sample_cycle()
            timeline.append(busy)
            if start_idx is None and timeline[-1] == 1:
                start_idx = len(timeline) - 1
            if (
                start_idx is not None
                and len(timeline) >= 2
                and timeline[-2] == 1
                and timeline[-1] == 0
            ):
                fall_idx = len(timeline) - 1
                break
        assert start_idx is not None, f"P2 calib: op1 busy never asserted (tail={timeline[-10:]})"
        assert fall_idx is not None, (
            f"P2 calib: TIMEOUT waiting op1 busy fall (tail={timeline[-10:]})"
        )
        hold = fall_idx - start_idx
        assert hold > 0, f"P2 calib: non-positive busy hold measured: {hold}"
        await self._wait_zeroer_idle()
        return hold

    async def _p2_race_cell(self, label: str, target_offset: int, busy_hold: int) -> dict:
        """One swept cell of SMC-CG-ZEROER-AXICLK.S1: trigger op1, fire the
        follow-on op2 trigger exactly `target_offset` clk_smc_i cycles
        relative to op1's own busy-falling edge (predicted from
        `busy_hold`, verified post-hoc against the actually observed fall
        -- never assumed), and observe axi_clk_enable continuity plus
        op2's outcome."""
        dut = self._dut()
        await self._wait_zeroer_idle()
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=0,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy",),
        )

        timeline: list[tuple[int, int]] = []

        async def _step() -> None:
            busy, en = await self._p2_sample_cycle()
            timeline.append((busy, en))

        trig1 = cocotb.start_soon(self._p2_trigger_op(P2_DEST_OP1, P2_OP_SIZE))
        while not trig1.done():
            await _step()
        start_idx = next((i for i, (b, _e) in enumerate(timeline) if b == 1), None)
        while start_idx is None:
            await _step()
            if timeline[-1][0] == 1:
                start_idx = len(timeline) - 1

        predicted_fall_idx = start_idx + busy_hold
        fire_after_idx = predicted_fall_idx - 1 + target_offset

        trig2 = None
        start_writes2 = None
        trigger_start_idx = None
        for _ in range(P2_TRIAL_TIMEOUT_SMC):
            await _step()
            cur_idx = len(timeline) - 1
            if trig2 is None and cur_idx >= fire_after_idx:
                start_writes2 = self._write_count()
                trigger_start_idx = cur_idx + 1
                trig2 = cocotb.start_soon(self._p2_trigger_op(P2_DEST_OP2, P2_OP_SIZE))
            if trig2 is not None and trig2.done():
                break
        else:
            raise AssertionError(f"{label}: TIMEOUT firing/completing follow-on trigger write")

        fall_idx = None
        for i in range(start_idx, len(timeline) - 1):
            if timeline[i][0] == 1 and timeline[i + 1][0] == 0:
                fall_idx = i + 1
                break
        assert fall_idx is not None, f"{label}: op1 busy fall not observed (tail={timeline[-10:]})"
        observed_offset = trigger_start_idx - fall_idx
        assert observed_offset == target_offset, (
            f"{label}: intended offset {target_offset} vs observed {observed_offset} "
            f"(start_idx={start_idx} busy_hold={busy_hold} fall_idx={fall_idx} "
            f"trigger_start_idx={trigger_start_idx})"
        )

        completed = False
        write_addr_phase_seen = False
        for _ in range(P2_FOLLOWON_BOUND_SMC):
            if timeline[-1][0] == 1:
                write_addr_phase_seen = True
            if (
                write_addr_phase_seen
                and timeline[-1][0] == 0
                and self._write_count() > start_writes2
            ):
                completed = True
                break
            await _step()

        # First enabled sample after op1's own busy assert (tolerates the
        # same <=1-cycle turn-on latency the P1 checkers already establish
        # for this signal -- not itself a "glitch").
        resume_idx = next(
            (i for i in range(start_idx, len(timeline)) if timeline[i][1] == 1),
            None,
        )
        assert resume_idx is not None, (
            f"{label}: axi_clk_enable never resumed after op1 busy assert "
            f"(start_idx={start_idx}, tail={timeline[start_idx : start_idx + 10]})"
        )
        assert resume_idx - start_idx <= 1, (
            f"{label}: axi_clk_enable resume not within 1 cycle of op1 busy "
            f"assert: delta={resume_idx - start_idx}"
        )
        last_busy_idx = max(i for i, (b, _e) in enumerate(timeline) if b == 1)

        # op2's own busy-reassertion edge, if observed within this cell's
        # captured timeline -- the boundary that separates "mid-busy" (still
        # in fail_on scope, rev2 unchanged) from "strictly between the two
        # busy pulses" (rev2 AMENDMENT: permitted, logged, never scored).
        op2_rise_idx = next(
            (i for i in range(fall_idx, len(timeline)) if timeline[i][0] == 1),
            None,
        )
        # op2's own turn-on latency: the same <=1-cycle axi_clk_enable
        # turn-on-after-busy-assert latency already established (and
        # PROVEN) for op1 via `resume_idx` above and for P1's own
        # `_measure_busy_window_toggles` (`delta <= 1`) applies symmetrically
        # to op2's busy reassertion -- this is the gater's known onset
        # latency, not a "mid-busy" deassert, so the mid-busy scan for op2
        # starts at op2's own resume sample, exactly mirroring op1's
        # resume_idx treatment above.
        op2_resume_idx = None
        if op2_rise_idx is not None:
            op2_resume_idx = next(
                (i for i in range(op2_rise_idx, len(timeline)) if timeline[i][1] == 1),
                None,
            )
            assert op2_resume_idx is not None, (
                f"{label}: axi_clk_enable never resumed after op2 busy assert "
                f"(op2_rise_idx={op2_rise_idx}, "
                f"tail={timeline[op2_rise_idx : op2_rise_idx + 10]})"
            )
            assert op2_resume_idx - op2_rise_idx <= 1, (
                f"{label}: axi_clk_enable resume not within 1 cycle of op2 "
                f"busy assert: delta={op2_resume_idx - op2_rise_idx}"
            )

        # Mid-busy glitch scope: op1's own busy tail (resume_idx..fall_idx-1)
        # plus, if observed, op2's own busy span from ITS resume sample
        # (op2_resume_idx..last_busy_idx). A deassert sample here means
        # axi_clk_enable==0 WHILE zeroer_busy_o==1 (post turn-on) for one of
        # the two operations -- exactly what CHK-ZEROER-AXICLK-NOGLITCH's
        # rev2 fail_on still forbids at every swept timing, no carve-out.
        mid_busy_ranges = [range(resume_idx, fall_idx)]
        if op2_resume_idx is not None:
            mid_busy_ranges.append(range(op2_resume_idx, last_busy_idx + 1))
        glitches = [i for rng in mid_busy_ranges for i in rng if timeline[i][1] == 0]
        # NOTE: a real mid-busy glitch here is a DUT/RTL finding (rev2's
        # NOGLITCH fail_on applies to the mid-busy segment at every swept
        # timing, no carve-out -- SF-005's evidence-only carve-out is scoped
        # to CHK-ZEROER-AXICLK-COMPLETION's protocol-outcome verdict only,
        # per the card). Do NOT raise here: the card's own fail_on also
        # independently fails the checker if "any of the 3 required cells
        # [is] not observed in the retained log", so aborting mid-sweep on
        # the first violation would trade one honest failure mode for a
        # worse one (missing cells). Record the violation and let all 3
        # cells run to completion so every cell's evidence reaches the kept
        # log; _p2_extension raises a single summary failure after emitting
        # checkers.
        glitch_detail = (
            f"{label}: axi_clk_enable deassert glitch WHILE zeroer_busy_o==1 "
            f"at indices {glitches} within busy span [{start_idx},{last_busy_idx}] "
            f"(tail={timeline[max(0, glitches[0] - 3) : glitches[0] + 5]})"
            if glitches
            else ""
        )

        # Inter-busy deassert gap: rev2 AMENDMENT -- axi_clk_enable is
        # PERMITTED to deassert strictly between op1's busy-fall (fall_idx)
        # and op2's busy-reassert (op2_rise_idx), for the duration of the
        # documented multi-write configure-then-trigger protocol's
        # turnaround. Logged (start cycle, end cycle, duration), never
        # scored as a failure, at each swept timing.
        gap_upper = op2_rise_idx if op2_rise_idx is not None else len(timeline)
        inter_busy_gap_start = None
        inter_busy_gap_end = None
        for i in range(fall_idx, gap_upper):
            if timeline[i][1] == 0:
                if inter_busy_gap_start is None:
                    inter_busy_gap_start = i
                inter_busy_gap_end = i
            elif inter_busy_gap_start is not None:
                break
        inter_busy_gap_duration = (
            inter_busy_gap_end - inter_busy_gap_start + 1 if inter_busy_gap_start is not None else 0
        )

        scored = target_offset in (0, 1)
        completion_detail = ""
        if scored and not completed:
            completion_detail = (
                f"{label}: follow-on op did not begin+complete within "
                f"{P2_FOLLOWON_BOUND_SMC} cycles (write_addr_phase_seen="
                f"{write_addr_phase_seen} writes_now={self._write_count()} "
                f"start_writes2={start_writes2} last_busy={timeline[-1][0]})"
            )

        return {
            "label": label,
            "target_offset": target_offset,
            "observed_offset": observed_offset,
            "glitches": len(glitches),
            "glitch_detail": glitch_detail,
            "inter_busy_gap_start": inter_busy_gap_start
            if inter_busy_gap_start is not None
            else -1,
            "inter_busy_gap_end": inter_busy_gap_end if inter_busy_gap_end is not None else -1,
            "inter_busy_gap_duration": inter_busy_gap_duration,
            "write_addr_phase_seen": int(write_addr_phase_seen),
            "completed": int(completed),
            "completion_detail": completion_detail,
            "writes_delta": self._write_count() - start_writes2,
            "scored": int(scored),
        }

    async def _p2_extension(self) -> None:
        """P2 extension (SMC_CG_P2_002), additive after the P1 flow in
        body(): back-to-back trigger race across axi_clk's busy-to-idle
        boundary."""
        cg.log_step(
            "P2-S1",
            "SETUP: re-confirm zeroer idle baseline (disable_cg=0, axi_clk "
            "gated, zeroer_busy_o=0) before the P2 back-to-back trigger race",
        )
        cg.mark_fence(self.fence, "SETUP")
        await self._program_cg(zeroer_en=True)
        await self._wait_zeroer_idle()
        await cg.wait_gated_off(
            self._dut(),
            "tb_zeroer_gated_axi_clk",
            hyst=0,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy",),
        )
        busy_hold = await self._p2_measure_busy_hold()
        cg.mark_fence(self.fence, "FIRST-OP-BUSY")

        cg.log_step(
            "P2-S2",
            "ACTION/RESPONSE/EFFECT for SMC-CG-ZEROER-AXICLK.S1: sweep the "
            f"follow-on trigger across busy_hold={busy_hold} cycles at "
            f"offsets {[o for _l, o in P2_CELLS]}",
        )
        results: dict[str, dict] = {}
        for label, offset in P2_CELLS:
            results[label] = await self._p2_race_cell(label, offset, busy_hold)
        cg.mark_fence(self.fence, "BOUNDARY-SWEEP(3-cells)")
        cg.mark_fence(self.fence, "FOLLOWON-OBSERVED")

        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-AXICLK-NOGLITCH",
            "CHK-ZEROER-AXICLK-NOGLITCH: "
            + " ".join(
                f"{label}(offset={r['observed_offset']},mid_busy_glitches={r['glitches']},"
                f"inter_busy_gap_start={r['inter_busy_gap_start']},"
                f"inter_busy_gap_end={r['inter_busy_gap_end']},"
                f"inter_busy_gap_duration={r['inter_busy_gap_duration']})"
                for label, r in results.items()
            ),
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-AXICLK-COMPLETION",
            "CHK-ZEROER-AXICLK-COMPLETION: "
            + " ".join(
                f"{label}(write_addr_phase_seen={r['write_addr_phase_seen']},"
                f"completed={r['completed']},writes_delta={r['writes_delta']},"
                f"scored={r['scored']})"
                for label, r in results.items()
            ),
        )

        cg.log_step(
            "P2-S3",
            "TIMEOUT: the bounded wait for the follow-on write-address "
            "phase has a finite bound, a fail-on-expiry path, and a "
            "last-state diagnostic",
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: calib_bound_smc_cycles={} trial_bound_smc_cycles={} "
            "followon_bound_smc_cycles={} expired=0 last_busy={} "
            "last_axi_clk_enable={}".format(
                P2_CALIB_TIMEOUT_SMC,
                P2_TRIAL_TIMEOUT_SMC,
                P2_FOLLOWON_BOUND_SMC,
                cg.sample_bit(self._dut(), "tb_zeroer_busy"),
                int(self._dut().tb_zeroer_gated_axi_clk.value),
            ),
        )

        expected_p2_pre_pass = [
            "SETUP",
            "FIRST-OP-BUSY",
            "BOUNDARY-SWEEP(3-cells)",
            "FOLLOWON-OBSERVED",
        ]
        p2_terms = [t for t, _ in self.fence if t in expected_p2_pre_pass]
        assert p2_terms == expected_p2_pre_pass, f"P2 NONVAC fence order wrong: {p2_terms}"

        # All 3 required cells' evidence is now in the kept log (checkers
        # emitted above). Fail the testcase, with a full summary, if any cell
        # recorded a real mid-busy glitch or a missed completion -- this would
        # be a DUT/RTL finding, not a test bug; per SMC_CG_P2_002 revision 2's
        # approved contract, the inter-busy deassert gap (logged above in
        # CHK-ZEROER-AXICLK-NOGLITCH's inter_busy_gap_* fields) is permitted
        # and therefore excluded from `violations` -- only a mid-busy glitch
        # (glitch_detail) or a missed same-cycle/1-after completion
        # (completion_detail) can fail this testcase.
        violations = [r["glitch_detail"] for r in results.values() if r["glitch_detail"]] + [
            r["completion_detail"] for r in results.values() if r["completion_detail"]
        ]
        assert not violations, (
            "SMC_CG_P2_002 boundary sweep found "
            f"{len(violations)} violation(s) after observing all 3 required "
            "cells (full per-cell evidence above in CHK-ZEROER-AXICLK-NOGLITCH/"
            "-COMPLETION lines): " + " | ".join(violations)
        )
        p2_nonvac_line = (
            "CHK-NONVAC: SETUP < FIRST-OP-BUSY < BOUNDARY-SWEEP(3-cells) < FOLLOWON-OBSERVED < PASS"
        )
        _LOG.info("%s", p2_nonvac_line)
        self.chk_seen["CHK-NONVAC-P2"] = p2_nonvac_line
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_zeroer_axiclk_cg_test_seq P2 extension PASS")

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_busy",
            "tb_output_axi_write_count",
            "rst_cool_ni",
            "rst_primary_smc_clk_no",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_MODEL_SIZE
            )
        await self._program_output_fabric_pass_all()
        await self._write_bytes(OUTPUT_FABRIC_ADDR, ZEROER_POISON)

        # ---- S1: idle gate-off within 1 cycle of idle establishment ----
        cg.log_step("S1", "disable_cg=0 (zeroer_cg_en=1), idle, observe axi_clk gates off")
        # Positive control: free-run via disable_cg=1, then drop enable to establish idle.
        await self._program_cg(zeroer_en=False)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 0
        await ClockCycles(dut.clk_smc_i, 4)
        free = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_axi_clk", 4)
        assert free == 4, f"axi_clk not free-running under disable_cg: {free}"
        # Arm: measure latency from tb_zeroer_cg_en==1 (idle disable_cg=0) to gated-off.
        await self._program_cg(zeroer_en=True)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0
        gate_off_lat = await cg.measure_gate_off_latency(
            dut,
            "tb_zeroer_gated_axi_clk",
            max_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
        )
        assert gate_off_lat <= 1, (
            f"axi_clk gate-off not within 1 cycle of idle: latency={gate_off_lat}"
        )
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE)
        assert edges == 0, f"axi_clk still toggling idle: {edges}"
        within_1 = int(gate_off_lat <= 1)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZAXI-GATE-OFF-IDLE",
            f"CHK-ZAXI-GATE-OFF-IDLE: gate_off_within_1cyc={within_1} "
            f"gate_off_latency={gate_off_lat} zero_toggles_idle={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "idle-gate-off-observed")

        # ---- S2: busy enables clock every cycle for entire busy window ----
        cg.log_step("S2", "trigger zeroer; axi_clk resumes for busy window")
        start_writes = self._write_count()
        delta, enabled_hits, post_resume_cycles = await self._measure_busy_window_toggles()
        assert delta <= 1, f"resume not within 1 cycle of busy: {delta}"
        assert post_resume_cycles > 0, "post-resume busy window empty"
        assert enabled_hits == post_resume_cycles, (
            f"axi_clk missing toggles after resume: hits={enabled_hits} "
            f"post_resume_cycles={post_resume_cycles}"
        )
        for _ in range(ZEROER_WAIT_CYCLES):
            if self._write_count() >= start_writes + 1 or cg.sample_bit(dut, "tb_zeroer_busy") == 0:
                break
            await ClockCycles(dut.clk_smc_i, 1)
        await self._wait_zeroer_idle()
        resume_ok = int(delta <= 1)
        every_ok = int(enabled_hits == post_resume_cycles)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZAXI-BUSY-ENABLE",
            f"CHK-ZAXI-BUSY-ENABLE: resume_within_1cyc={resume_ok} resume_cyc={delta} "
            f"toggles_every_cycle={every_ok} enabled_hits={enabled_hits} "
            f"post_resume_cycles={post_resume_cycles}",
        )
        cg.mark_fence(self.fence, "busy-enable-observed")

        # Re-settle idle gated.
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=0,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
        )

        # ---- S3: disable_cg=1 (zeroer_cg_en=0) keeps clock on ----
        cg.log_step("S3", "zeroer_cg_en=0 (disable_cg=1); idle axi_clk stays enabled")
        await self._program_cg(zeroer_en=False)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 0
        await ClockCycles(dut.clk_smc_i, 4)
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE)
        assert edges == IDLE_OBSERVE, (
            f"axi_clk gated while disable_cg=1: edges={edges} window={IDLE_OBSERVE}"
        )
        toggles_every = int(edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZAXI-DISABLE-CG",
            f"CHK-ZAXI-DISABLE-CG: toggles_every_cycle={toggles_every} "
            f"edges={edges} window={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "disable-cg-observed")

        # ---- S4: reset override — cool reset asserts ~rst_ni ----
        cg.log_step("S4", "re-enable CG, gate off, assert cool reset; axi_clk enabled")
        await self._program_cg(zeroer_en=True)
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=0,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
        )
        # Assert cool reset (frontdoor).
        dut.rst_cool_ni.value = 0
        # Wait for primary reset to assert (active-low out).
        for _ in range(BUSY_TIMEOUT_SMC):
            if int(dut.rst_primary_smc_clk_no.value) == 0:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError("TIMEOUT waiting rst_primary_smc_clk_no assert")
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE)
        assert edges == IDLE_OBSERVE, (
            f"axi_clk gated during reset: edges={edges} "
            f"rst_primary={int(dut.rst_primary_smc_clk_no.value)}"
        )
        toggles_rst = int(edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZAXI-RESET-OVERRIDE",
            f"CHK-ZAXI-RESET-OVERRIDE: toggles_during_reset={toggles_rst} "
            f"edges={edges} window={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "reset-override-observed")
        # Release reset and allow bring-up to settle for subsequent VIP bookkeeping.
        dut.rst_cool_ni.value = 1
        for _ in range(BUSY_TIMEOUT_SMC):
            if int(dut.rst_primary_smc_clk_no.value) == 1:
                break
            await RisingEdge(dut.clk_smc_i)
        await ClockCycles(dut.clk_smc_i, 32)

        cg.assert_fence_order(
            self.fence,
            [
                "idle-gate-off-observed",
                "busy-enable-observed",
                "disable-cg-observed",
                "reset-override-observed",
            ],
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: idle-gate-off-observed < busy-enable-observed < "
            "disable-cg-observed < reset-override-observed < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_zeroer_axiclk_cg_test_seq PASS")

        # ---- P2 (SMC_CG_P2_002) extension: additive, P1 evidence above unchanged ----
        await self._p2_extension()
