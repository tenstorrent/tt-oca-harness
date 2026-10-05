# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_ZEROER_AXICLK_CG_TEST ANCHOR: smc_zeroer_axiclk_cg_test

DV-CARD: SMC_CG_P2_002 ANCHOR: smc_zeroer_axiclk_cg_test

The P2 card shares this anchor: the P1 steps and checkers run first and emit
their evidence tokens verbatim; `_p2_extension`, called once at the end of
body(), adds the busy-to-idle back-to-back trigger race.

Two verdicts are applied to the swept cells, and BOTH are applied at all three
timings. The retained tokens carry a `*_scored` field per cell so the log states
the verdict that actually ran:

* COMPLETION -- the follow-on op must start and complete a write to its own
  destination `P2_DEST_OP2`, at every swept timing including the
  1-cycle-before overlap (`completion_scored=1`).
* MID-BUSY GLITCH -- while zeroer_busy_o==1 for either operation,
  axi_clk_enable must stay asserted, at every swept timing
  (`mid_busy_glitch_scored=1`).

The one carve-out is neither of those: a deassert gap STRICTLY BETWEEN the two
busy pulses is permitted and logged, never scored -- see below.

CHK-ZEROER-AXICLK-NOGLITCH is scoped to the busy spans, not to the whole
busy-to-idle boundary: the 3-write DEST_ADDR->SIZE->CTRL_STATUS trigger protocol
has a multi-cycle turnaround through this frontdoor, so a deassert gap between
the two busy pulses is inherent at every swept timing regardless of the DUT.

The scored claim is therefore: while zeroer_busy_o==1 for EITHER operation
(op1's tail or op2's own busy span), axi_clk_enable must stay asserted with zero
deassert -- no mid-busy glitch -- at all 3 swept timings, with no carve-out for
this half of the checker. A deassert gap STRICTLY BETWEEN the two busy pulses,
caused by the multi-write trigger protocol's turnaround latency, is PERMITTED
and must be LOGGED (start cycle, end cycle, duration) at each swept timing --
never scored as a failure.
`_p2_race_cell` below implements this split by classifying every deasserted
(enable==0) sample as either "mid-busy" (busy==1 at that sample -- fail_on
scope) or "inter-busy gap" (busy==0, strictly between op1's busy-fall and
op2's busy-reassert -- logged, not scored), never by which swept timing is
under test.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

HYST = 8
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
BUSY_TIMEOUT_SMC = 256
ZEROER_WAIT_CYCLES = 200
# Bound on the frontdoor accesses that program the gate enable, from the start
# of the latency sampling task to the enable's rising edge.
ENABLE_EDGE_TIMEOUT_SMC = 256

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

# P2 (SMC_CG_P2_002) cells: back-to-back trigger race vs the axi_clk
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
        self._p2_calib_cycles_used = -1

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

    def _last_write_addr(self) -> int:
        """AW address of the most recently B-responded output-AXI write.

        `tb_top.sv:1085-1086` latches the counter and this address together on
        the same B handshake, so pairing them attributes a counted write to the
        destination it went to. A bare counter increment cannot: the counter is
        shared by every write on the output port, so op1's own response
        satisfies `count > start` even if op2 never wrote anything
        ([EXACT-EXPECTATION]).
        """
        return int(self._dut().tb_output_axi_last_addr.value)

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
        (never a hand literal)."""
        await self._wait_zeroer_idle()
        timeline: list[int] = []
        task = cocotb.start_soon(self._p2_trigger_op(P2_DEST_CALIB, P2_OP_SIZE))
        # Bounded: the CSR trigger writes are DUT responses (each waits for its
        # own B-response), so this loop must expire and raise with a last-state
        # diagnostic rather than spin until the runner's wall-clock timeout
        # ([TIMEOUT-MUST-FAIL]).
        trigger_wait = 0
        while not task.done():
            trigger_wait += 1
            if trigger_wait > P2_CALIB_TIMEOUT_SMC:
                raise AssertionError(
                    f"P2 calib: TIMEOUT waiting the 3-write trigger sequence to "
                    f"complete within {P2_CALIB_TIMEOUT_SMC} smc cycles "
                    f"(busy={cg.sample_bit(self._dut(), 'tb_zeroer_busy')} "
                    f"axi_clk_enable="
                    f"{int(self._dut().tb_zeroer_gated_axi_clk.value)} "
                    f"tail={timeline[-10:]})"
                )
            busy, _en = await self._p2_sample_cycle()
            timeline.append(busy)
        start_idx = next((i for i, b in enumerate(timeline) if b == 1), None)
        fall_idx = None
        calib_used = 0
        for _ in range(P2_CALIB_TIMEOUT_SMC):
            calib_used += 1
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
        # MEASURED margin against P2_CALIB_TIMEOUT_SMC, reported in
        # CHK-TIMEOUT-PATHS instead of restating the bound constant.
        self._p2_calib_cycles_used = calib_used
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
        # Both waits below are on DUT responses (the trigger writes' own
        # B-responses, then zeroer_busy_o rising). Each is bounded and raises
        # with a last-state diagnostic on expiry ([TIMEOUT-MUST-FAIL]).
        trig1_wait = 0
        while not trig1.done():
            trig1_wait += 1
            if trig1_wait > P2_TRIAL_TIMEOUT_SMC:
                raise AssertionError(
                    f"{label}: TIMEOUT waiting op1's 3-write trigger sequence to "
                    f"complete within {P2_TRIAL_TIMEOUT_SMC} smc cycles "
                    f"(busy={cg.sample_bit(dut, 'tb_zeroer_busy')} "
                    f"axi_clk_enable={int(dut.tb_zeroer_gated_axi_clk.value)} "
                    f"tail={timeline[-10:]})"
                )
            await _step()
        start_idx = next((i for i, (b, _e) in enumerate(timeline) if b == 1), None)
        busy_rise_wait = 0
        while start_idx is None:
            busy_rise_wait += 1
            if busy_rise_wait > P2_TRIAL_TIMEOUT_SMC:
                raise AssertionError(
                    f"{label}: TIMEOUT waiting op1 zeroer_busy_o to assert within "
                    f"{P2_TRIAL_TIMEOUT_SMC} smc cycles after its trigger write "
                    f"(busy={cg.sample_bit(dut, 'tb_zeroer_busy')} "
                    f"axi_clk_enable={int(dut.tb_zeroer_gated_axi_clk.value)} "
                    f"tail={timeline[-10:]})"
                )
            await _step()
            if timeline[-1][0] == 1:
                start_idx = len(timeline) - 1

        predicted_fall_idx = start_idx + busy_hold
        fire_after_idx = predicted_fall_idx - 1 + target_offset

        trig2 = None
        start_writes2 = None
        trigger_start_idx = None
        trial_used = 0
        for _ in range(P2_TRIAL_TIMEOUT_SMC):
            trial_used += 1
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
        followon_used = 0
        completion_addr = -1
        for _ in range(P2_FOLLOWON_BOUND_SMC):
            followon_used += 1
            if timeline[-1][0] == 1:
                write_addr_phase_seen = True
            if (
                write_addr_phase_seen
                and timeline[-1][0] == 0
                and self._write_count() > start_writes2
            ):
                # ATTRIBUTED completion: the write that was counted must be the
                # one op2 issued, identified by its own destination address.
                completion_addr = self._last_write_addr()
                completed = completion_addr == P2_DEST_OP2
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
        # in scoring scope) from "strictly between the two busy pulses"
        # (permitted, logged, never scored).
        op2_rise_idx = next(
            (i for i in range(fall_idx, len(timeline)) if timeline[i][0] == 1),
            None,
        )
        # op2's own turn-on latency: the gater's <=1-cycle axi_clk_enable onset
        # after busy assert (asserted for op1 via `resume_idx` above) applies to
        # op2's busy reassertion too, so the mid-busy scan for op2 starts at
        # op2's own resume sample.
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
        # scored claim forbids at every swept timing, no carve-out.
        mid_busy_ranges = [range(resume_idx, fall_idx)]
        if op2_resume_idx is not None:
            mid_busy_ranges.append(range(op2_resume_idx, last_busy_idx + 1))
        glitches = [i for rng in mid_busy_ranges for i in rng if timeline[i][1] == 0]
        # A mid-busy glitch is recorded here and raised by `_p2_extension` after
        # every cell has emitted its evidence: the card requires all 3 cells in
        # the kept log, so aborting on the first violation would lose the
        # remaining cells' evidence.
        glitch_detail = (
            f"{label}: axi_clk_enable deassert glitch WHILE zeroer_busy_o==1 "
            f"at indices {glitches} within busy span [{start_idx},{last_busy_idx}] "
            f"(tail={timeline[max(0, glitches[0] - 3) : glitches[0] + 5]})"
            if glitches
            else ""
        )

        # Inter-busy deassert gap: axi_clk_enable is
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

        # The completion verdict is applied at every swept timing, including the
        # 1-cycle-before overlap; the token's `completion_scored=1` field says
        # so, so the retained evidence describes the verdict that ran.
        completion_detail = ""
        if not completed:
            completion_detail = (
                f"{label}: follow-on op did not begin+complete a write to "
                f"0x{P2_DEST_OP2:x} within {P2_FOLLOWON_BOUND_SMC} cycles "
                f"(write_addr_phase_seen={write_addr_phase_seen} "
                f"last_write_addr=0x{completion_addr:x} "
                f"writes_now={self._write_count()} "
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
            "completion_addr": completion_addr,
            "completion_detail": completion_detail,
            "writes_delta": self._write_count() - start_writes2,
            # MEASURED margins against the two bounded waits in this cell.
            "trial_cycles_used": trial_used,
            "followon_cycles_used": followon_used,
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
                f"inter_busy_gap_duration={r['inter_busy_gap_duration']},"
                f"mid_busy_glitch_scored=1)"
                for label, r in results.items()
            ),
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-AXICLK-COMPLETION",
            "CHK-ZEROER-AXICLK-COMPLETION: "
            + " ".join(
                f"{label}(write_addr_phase_seen={r['write_addr_phase_seen']},"
                f"completed={r['completed']},"
                f"last_write_addr=0x{r['completion_addr']:x},"
                f"expected_dest=0x{P2_DEST_OP2:x},"
                f"writes_delta={r['writes_delta']},completion_scored=1)"
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
            "CHK-TIMEOUT-PATHS: calib_cycles_used={}/{} bound; "
            "trial_cycles_used={} max={}/{} bound; "
            "followon_cycles_used={} max={}/{} bound; "
            "last_busy={} last_axi_clk_enable={}".format(
                self._p2_calib_cycles_used,
                P2_CALIB_TIMEOUT_SMC,
                ",".join(str(r["trial_cycles_used"]) for r in results.values()),
                max(r["trial_cycles_used"] for r in results.values()),
                P2_TRIAL_TIMEOUT_SMC,
                ",".join(str(r["followon_cycles_used"]) for r in results.values()),
                max(r["followon_cycles_used"] for r in results.values()),
                P2_FOLLOWON_BOUND_SMC,
                cg.sample_bit(self._dut(), "tb_zeroer_busy"),
                int(self._dut().tb_zeroer_gated_axi_clk.value),
            ),
        )

        # DUT-time claim over the P2 phases that bracket real simulation time.
        # `FOLLOWON-OBSERVED` is marked at the same instant as
        # `BOUNDARY-SWEEP(3-cells)` (the sweep is the follow-on observation), so
        # it is outside the strictly-increasing list; its evidence is the
        # per-cell completion/writes_delta asserted below.
        expected_p2_timed = ["SETUP", "FIRST-OP-BUSY", "BOUNDARY-SWEEP(3-cells)"]
        p2_fence = [(t, ts) for t, ts in self.fence if t in expected_p2_timed]
        p2_times = cg.assert_fence_progress(p2_fence, expected_p2_timed)
        followon = [ts for t, ts in self.fence if t == "FOLLOWON-OBSERVED"]
        assert len(followon) == 1, f"FOLLOWON-OBSERVED marked {len(followon)} time(s)"

        # Every cell's evidence is in the kept log (checkers emitted above);
        # fail the testcase with a full summary if any cell recorded a mid-busy
        # glitch or a missed completion. Per SMC_CG_P2_002 the inter-busy
        # deassert gap (logged in CHK-ZEROER-AXICLK-NOGLITCH's inter_busy_gap_*
        # fields) is permitted and excluded from `violations`.
        violations = [r["glitch_detail"] for r in results.values() if r["glitch_detail"]] + [
            r["completion_detail"] for r in results.values() if r["completion_detail"]
        ]
        assert not violations, (
            "SMC_CG_P2_002 boundary sweep found "
            f"{len(violations)} violation(s) after observing all 3 required "
            "cells (full per-cell evidence above in CHK-ZEROER-AXICLK-NOGLITCH/"
            "-COMPLETION lines): " + " | ".join(violations)
        )
        # Measured contrast carried inside the token: every swept cell must have
        # actually observed its follow-on write-address phase and completed at
        # least one write, and busy_hold must be a real, non-zero measurement.
        # A vacuous sweep (no cell reaching the DUT) fails here, not silently.
        assert busy_hold > 0, f"P2 busy_hold measured as {busy_hold} cycles"
        cells_completed = sum(r["completed"] for r in results.values())
        cells_writes = sum(r["writes_delta"] for r in results.values())
        assert len(results) == len(P2_CELLS) and cells_writes > 0, (
            f"P2 sweep vacuous: cells={len(results)}/{len(P2_CELLS)} "
            f"writes_delta_total={cells_writes}"
        )
        assert cells_completed == len(P2_CELLS), (
            f"FOLLOWON-OBSERVED unproven: only {cells_completed}/{len(P2_CELLS)} "
            f"swept cells completed their follow-on operation"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC-P2",
            "CHK-NONVAC-P2: SETUP@{}ns < FIRST-OP-BUSY@{}ns < "
            "BOUNDARY-SWEEP(3-cells)@{}ns (FOLLOWON-OBSERVED@{}ns) < PASS "
            "busy_hold={} cells={} completed={} writes_delta_total={}".format(
                p2_times[0],
                p2_times[1],
                p2_times[2],
                followon[0],
                busy_hold,
                len(results),
                cells_completed,
                cells_writes,
            ),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_zeroer_axiclk_cg_test_seq P2 extension PASS")

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
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0
        # The latency origin is the enable's own rising edge on
        # tb_zeroer_cg_en: the sampling task starts before the enable write,
        # so the frontdoor accesses that program the enable cannot move it.
        gate_off = cocotb.start_soon(
            cg.measure_gate_off_from_enable(
                dut,
                "tb_zeroer_cg_en",
                "tb_zeroer_gated_axi_clk",
                enable_wait_smc=ENABLE_EDGE_TIMEOUT_SMC,
                max_smc=GATE_OFF_TIMEOUT_SMC,
                diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
            )
        )
        await self._program_cg(zeroer_en=True)
        enable_at, gate_off_lat = await gate_off
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        assert gate_off_lat <= 1, (
            f"axi_clk gate-off not within 1 cycle of tb_zeroer_cg_en rising: latency={gate_off_lat}"
        )
        idle_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE
        )
        edges = idle_enabled
        assert edges == 0, f"axi_clk still toggling idle: {edges}"
        within_1 = int(gate_off_lat <= 1)
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZAXI-GATE-OFF-IDLE",
            f"CHK-ZAXI-GATE-OFF-IDLE: gate_off_within_1cyc={within_1} "
            f"gate_off_latency={gate_off_lat} origin=tb_zeroer_cg_en_rise "
            f"enable_edge_sample={enable_at} zero_toggles_idle={IDLE_OBSERVE}",
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
        disable_cg_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE
        )
        edges = disable_cg_enabled
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
        # Assert cool reset (frontdoor); the primary reset follows it through
        # the reference-clock de-glitcher.
        dut.rst_cool_ni.value = 0
        await cg.wait_reset_asserted(
            dut,
            "rst_primary_smc_clk_no",
            ref_cycles=cg.COOL_RESET_ASSERT_BOUND_REF_CYCLES,
            ref_period_ns=self.cfg.ref_clk_period_ns,
        )
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
        # Release reset and allow bring-up to settle for subsequent VIP
        # bookkeeping. Bounded AND fail-on-expiry, matching the assert twin at
        # the top of S4: a DUT that never releases the primary reset must fail
        # at the wait that expired, not later and elsewhere
        # ([TIMEOUT-MUST-FAIL]).
        dut.rst_cool_ni.value = 1
        for _ in range(BUSY_TIMEOUT_SMC):
            if int(dut.rst_primary_smc_clk_no.value) == 1:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(
                f"TIMEOUT waiting rst_primary_smc_clk_no deassert within "
                f"{BUSY_TIMEOUT_SMC} smc cycles after rst_cool_ni release "
                f"(rst_cool_ni={int(dut.rst_cool_ni.value)} "
                f"rst_primary_smc_clk_no="
                f"{int(dut.rst_primary_smc_clk_no.value)} "
                f"axi_clk_enable={int(dut.tb_zeroer_gated_axi_clk.value)})"
            )
        await ClockCycles(dut.clk_smc_i, 32)

        # ---- S5: reset released -> the gater takes the clock back ----
        # S5 measures whether the gater re-gates once the reset override is
        # released: same probe, same IDLE_OBSERVE window as S4. A gater that
        # latches the reset override reads IDLE_OBSERVE here and fails at
        # CHK-NONVAC below. Both waits are bounded and raise on expiry.
        await self._program_cg(zeroer_en=False)
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 0
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0
        # Same origin as S1: the enable's own rising edge, sampled by a task
        # that starts before the enable write.
        post_reset_gate_off = cocotb.start_soon(
            cg.measure_gate_off_from_enable(
                dut,
                "tb_zeroer_cg_en",
                "tb_zeroer_gated_axi_clk",
                enable_wait_smc=ENABLE_EDGE_TIMEOUT_SMC,
                max_smc=GATE_OFF_TIMEOUT_SMC,
                diag_names=(
                    "tb_zeroer_busy",
                    "tb_zeroer_cg_en",
                    "rst_primary_smc_clk_no",
                ),
            )
        )
        await self._program_cg(zeroer_en=True)
        _, post_reset_gate_off_lat = await post_reset_gate_off
        post_reset_idle_enabled = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE
        )
        cg.mark_fence(self.fence, "post-reset-regate-observed")

        # `assert_fence_progress` requires strictly increasing simulation
        # timestamps across the listed phases (order alone holds by
        # construction) and returns them for the token below.
        fence_times = cg.assert_fence_progress(
            self.fence,
            [
                "idle-gate-off-observed",
                "busy-enable-observed",
                "disable-cg-observed",
                "reset-override-observed",
                "post-reset-regate-observed",
            ],
        )
        # `post_reset_idle_enabled` (S5) against `edges` (S4) on the same probe
        # (tb_zeroer_gated_axi_clk) over the same IDLE_OBSERVE window: reset
        # asserted -> IDLE_OBSERVE/IDLE_OBSERVE enabled, reset released and the
        # block idle -> 0/IDLE_OBSERVE. A gater that latches its reset override,
        # or never re-gates after a reset cycle, fails here.
        assert post_reset_idle_enabled == 0 and edges == IDLE_OBSERVE, (
            f"NONVAC reset-override contrast absent on tb_zeroer_gated_axi_clk: "
            f"reset_override_enabled={edges}/{IDLE_OBSERVE} then, after reset "
            f"release with the Zeroer idle and zeroer_cg_en=1, "
            f"post_reset_idle_enabled={post_reset_idle_enabled}/{IDLE_OBSERVE} "
            f"(gate-off latency after release={post_reset_gate_off_lat})"
        )
        # Refactor guards: `idle_enabled == 0` restates S1's assert,
        # `disable_cg_enabled == IDLE_OBSERVE` restates S3's, and `enabled_hits
        # == post_resume_cycles` restates S2's. They fail if a refactor drops an
        # upstream assert, and the values they carry into the token are the
        # evidence a reader falsifies the claim from.
        assert idle_enabled == 0 and disable_cg_enabled == IDLE_OBSERVE, (
            f"NONVAC contrast absent on tb_zeroer_gated_axi_clk: "
            f"idle_enabled={idle_enabled}/{IDLE_OBSERVE} "
            f"disable_cg_enabled={disable_cg_enabled}/{IDLE_OBSERVE}"
        )
        assert post_resume_cycles > 0 and enabled_hits == post_resume_cycles, (
            f"NONVAC busy-window measurement vacuous: enabled_hits="
            f"{enabled_hits} post_resume_cycles={post_resume_cycles}"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: idle-gate-off-observed@{}ns < busy-enable-observed@{}ns "
            "< disable-cg-observed@{}ns < reset-override-observed@{}ns "
            "< post-reset-regate-observed@{}ns < PASS "
            "idle_enabled={}/{} busy_enabled={}/{} disable_cg_enabled={}/{} "
            "reset_override_enabled={}/{} "
            "post_reset_gate_off_latency={} (origin=tb_zeroer_cg_en_rise) "
            "post_reset_idle_enabled={}/{}".format(
                fence_times[0],
                fence_times[1],
                fence_times[2],
                fence_times[3],
                fence_times[4],
                idle_enabled,
                IDLE_OBSERVE,
                enabled_hits,
                post_resume_cycles,
                disable_cg_enabled,
                IDLE_OBSERVE,
                edges,
                IDLE_OBSERVE,
                post_reset_gate_off_lat,
                post_reset_idle_enabled,
                IDLE_OBSERVE,
            ),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_zeroer_axiclk_cg_test_seq PASS")

        # ---- P2 (SMC_CG_P2_002) extension ----
        await self._p2_extension()
