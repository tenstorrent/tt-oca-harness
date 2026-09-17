# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_DMA_CG_ACTIVITY_TEST ANCHOR: smc_dma_cg_activity_test

DV-CARD: SMC_CG_P2_001 ANCHOR: smc_dma_cg_activity_test

The P2 card extends this same anchor: the P1 steps and checkers in body() keep
their evidence tokens verbatim, and the P2 extension (_p2_extension) adds the
full-range hysteresis sweep {0,1,32,63,64} and the activity-reassert race,
called once at the end of body(). CG_HYSTERESIS_W==6 (hw/sys/smc/doc/dma.adoc)
-- gap=64 exercises the
field's own truncation (64 & 0x3F == 0), not a TB special case, and its
expectation is the truncated value 0, not a `<= 63` bound that no RTL can
violate.

Sweep gaps {0, 1, 32, 63, 64} plus seed extras are all driven and all exactly
asserted, but only {32, 63, 64} are BOOKED as covered cells: the 0..8 band is
carried as UNPROVEN and must not be counted as covered by any closure
report -- see P2_LOW_BAND_EXCLUSION_REASON.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG

# Every record this sequence emits goes through `cocotb.log`: a module-level
# `logging.getLogger(__name__)` is not captured by the cocotb/pyuvm runner, so
# the STEP/CHK/FENCE and P2_COVERAGE_ARTIFACT evidence written through one never
# reaches the kept log ([EVIDENCE-TOKEN-CONDITIONAL]).


def _p2_coverage_report_dirs() -> list[Path]:
    """Prefer the run's log/coverage dirs so the artifact sits beside the kept log."""
    candidates: list[Path] = []
    env_dir = os.environ.get("SMC_DV_RUN_LOGDIR")
    if env_dir:
        candidates.append(Path(env_dir))
    results = os.environ.get("COCOTB_RESULTS_FILE")
    if results:
        item_dir = Path(results).resolve().parent.parent
        candidates.append(item_dir / "logs")
        candidates.append(item_dir / "coverage")
    cwd = Path.cwd()
    candidates.append(cwd / "logs")
    candidates.append(cwd / "coverage")
    candidates.append(cwd)
    seen: set[Path] = set()
    out: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _emit_p2_hyst_sweep_coverage_report(
    cells_hit: list[str], cell_measurements: dict[str, dict[str, int]]
) -> Path:
    """Functional-coverage-report for SMC-CG-DMA-HYST.S1 required_cells.

    ``cells_hit`` must be derived from the sweep results (a cell is hit only
    after its exact deassert-cycle compare PASSED), never restated from the
    required list -- otherwise the artifact records intent, not measurement
    ([EVIDENCE-TOKEN-CONDITIONAL]). ``cell_measurements`` carries the observed
    numbers behind each hit so the artifact is auditable on its own.
    """
    required = [f"hyst-gap={g}" for g in P2_REQUIRED_SWEEP_GAPS]
    payload = {
        "artifact_type": "functional-coverage-report",
        "feature_key": "SMC-CG-DMA-HYST.S1",
        "method": "RANDOMIZED",
        "seed": int(os.environ.get("RANDOM_SEED", os.environ.get("SEED", "1")), 0),
        "required_cells": required,
        "cells_hit": cells_hit,
        "cell_measurements": cell_measurements,
        "excluded_cells": [f"hyst-gap={g}" for g in P2_LOW_BAND_SWEEP_GAPS],
        "excluded_reason": P2_LOW_BAND_EXCLUSION_REASON,
        "satisfied": set(cells_hit) >= set(required),
    }
    text = json.dumps(payload, indent=2) + "\n"
    written: list[Path] = []
    for out_dir in _p2_coverage_report_dirs():
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "functional-coverage-report.json"
            out_path.write_text(text, encoding="utf-8")
            written.append(out_path)
        except OSError:
            continue
    if not written:
        raise AssertionError("failed to write functional-coverage-report.json")
    cocotb.log.info(
        "P2_COVERAGE_ARTIFACT: functional-coverage-report.json path=%s cells=%s",
        written[0],
        ",".join(cells_hit),
    )
    return written[0]


# Authoritative addresses / field masks (generated headers via smc_addr_map).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK

DMA_CTRL_CONFIG = _addr.DMA_CTRL_CONFIG
DMA_CTRL_STATUS_0 = _addr.DMA_CTRL_STATUS_0
DMA_CTRL_NEXT_ID_0 = _addr.DMA_CTRL_NEXT_ID_0
DMA_CTRL_DONE_0 = _addr.DMA_CTRL_DONE_0
DMA_CTRL_DST_ADDRESS_LO = _addr.DMA_CTRL_DST_ADDRESS_LO
DMA_CTRL_DST_ADDRESS_HI = _addr.DMA_CTRL_DST_ADDRESS_HI
DMA_CTRL_SRC_ADDRESS_LO = _addr.DMA_CTRL_SRC_ADDRESS_LO
DMA_CTRL_SRC_ADDRESS_HI = _addr.DMA_CTRL_SRC_ADDRESS_HI
DMA_CTRL_LENGTH_LO = _addr.DMA_CTRL_LENGTH_LO
DMA_CTRL_LENGTH_HI = _addr.DMA_CTRL_LENGTH_HI
DMA_CTRL_DST_STRIDE_LO = _addr.DMA_CTRL_DST_STRIDE_LO
DMA_CTRL_DST_STRIDE_HI = _addr.DMA_CTRL_DST_STRIDE_HI
DMA_CTRL_SRC_STRIDE_LO = _addr.DMA_CTRL_SRC_STRIDE_LO
DMA_CTRL_SRC_STRIDE_HI = _addr.DMA_CTRL_SRC_STRIDE_HI
DMA_CTRL_NUM_REPETITIONS_LO = _addr.DMA_CTRL_NUM_REPETITIONS_LO
DMA_CTRL_NUM_REPETITIONS_HI = _addr.DMA_CTRL_NUM_REPETITIONS_HI
DMA_CONFIG_ENABLED_ND = _addr.DMA_CONFIG_ENABLED_ND

INBOUND0_FILTER_CONFIG = _addr.INBOUND0_FILTER_CONFIG
INBOUND0_START = _addr.INBOUND0_START
INBOUND0_END = _addr.INBOUND0_END
OUTBOUND0_FILTER_CONFIG = _addr.OUTBOUND0_FILTER_CONFIG
OUTBOUND0_START = _addr.OUTBOUND0_START
OUTBOUND0_END = _addr.OUTBOUND0_END

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0100
DMA_MODEL_REGION = "dma_cg_output_fabric"
DMA_MODEL_SIZE = 0x2000
# S2: short transfer. S3: longer so frontend can clear while backend remains busy.
DMA_PAYLOAD_S2 = bytes.fromhex("A1B2C3D4E5F60708")
DMA_PAYLOAD_S3 = bytes([(i * 17) & 0xFF for i in range(256)])

# Directed hysteresis for measurable gate-off (DIRECTED scenarios).
HYST_CYCLES = 8
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
RESUME_TIMEOUT_SMC = 64
BACKEND_ONLY_TIMEOUT_SMC = 512
# S3: observe every-cycle toggles across a multi-cycle backend-only window.
S3_MEASURE_WINDOW = 8

# P2 (SMC_CG_P2_001) additions: hysteresis full-range sweep + reassert race.
# Cells GRADED for SMC-CG-DMA-HYST.S1: 32-mid, 63-max, 64-just-over-max
# (the last exercises the 6-bit CG_HYSTERESIS_W field's own truncation).
# Seed-driven extras (inventory random_knobs: hysteresis_value) are appended
# on top of these anchors so required_cells stay closed every seed.
P2_REQUIRED_SWEEP_GAPS = (32, 63, 64)

# The cells this testcase INTENDS to book, written out as an independent
# literal rather than derived from P2_REQUIRED_SWEEP_GAPS or from the booked
# `cells_hit` list. This is the expected side of the booked-cell check and of
# the SWEEP-COMPLETE fence term; deriving both sides from `cells_hit` would
# make that comparison equal by construction ([NO-ALWAYS-PASS-CHECKER]), so a
# silent change to the required tuple, to the sweep loop, or to the `cells_hit`
# construction must fail here instead of quietly renaming the fence term.
P2_GRADED_CELL_NAMES = ("hyst-gap=32", "hyst-gap=63", "hyst-gap=64")

# The 0..8 hysteresis band is SWEPT at 0 and 1 and exactly asserted below, but
# it is NOT booked as covered by this testcase's coverage artifact: the DMA
# command never completes at legal hysteresis 0 and 1 when dma_cg_en=1, so the
# within-1-cycle hysteresis-scaling proof holds for 9..63 only. Booking
# `hyst-gap=0` / `hyst-gap=1` as hit here would claim coverage of a band whose
# DUT behaviour is not established, so the two gaps stay as stimulus and as a
# fail-capable compare.
P2_LOW_BAND_SWEEP_GAPS = (0, 1)
P2_LOW_BAND_EXCLUSION_REASON = (
    "DMA command never completes at legal hysteresis 0 and 1 when "
    "dma_cg_en=1: the 0..8 hysteresis band is UNPROVEN and must not be counted "
    "as covered by any closure report. Swept and exactly asserted here, but "
    "not booked."
)

P2_NUM_RANDOM_GAPS = 3
# Bound derivations (a bound with no derivation is an unqualified magic number).
# Worst-case sweep observation window: max hysteresis 63 clk_smc_i cycles of
# countdown + the CSR-read activity pulse and its gater-busy tail, rounded up.
P2_SWEEP_MAX_CYCLES = 130
# Trailing cycles scanned after the last activity de-assert, >= max hysteresis
# 63 plus margin, so the deassert edge is always inside the captured timeline.
P2_SWEEP_TRAIL_MARGIN = 90
# Idle-settle bound: max hysteresis 63 + the DMA frontend/backend drain, with
# ~3x margin so a slow drain fails loudly instead of racing the next step.
P2_SETTLE_TIMEOUT_SMC = 200
P2_RACE_HYST_DEFAULT = 40
P2_RACE_EARLY_OFFSET_DEFAULT = 4
P2_RACE_B2B_OFFSET_DEFAULT = 1
P2_RACE_LATE_MARGIN_DEFAULT = 5
# Extra cycles beyond the programmed hysteresis allowed for the final
# countdown to expire after the last re-assert (countdown restart + settle).
P2_RACE_FINAL_MARGIN = 20
# Bound on waiting for a single activity pulse to be observed on the gater;
# an activity pulse that never appears within this many cycles is a failure.
P2_RACE_PULSE_BOUND = 200


def _p2_seeded_knobs(seed: int) -> tuple[tuple[int, ...], int, int, int, int]:
    """Return (sweep_gaps, race_hyst, early_off, b2b_off, late_margin)."""
    rng = random.Random(seed ^ 0x0DAC_C6A7)
    extras: list[int] = []
    anchors = tuple(P2_LOW_BAND_SWEEP_GAPS) + tuple(P2_REQUIRED_SWEEP_GAPS)
    while len(extras) < P2_NUM_RANDOM_GAPS:
        gap = rng.randint(2, 62)
        if gap not in anchors and gap not in extras:
            extras.append(gap)
    sweep = tuple(list(anchors) + extras)
    race_hyst = rng.randint(24, 55)
    early = rng.randint(2, 8)
    b2b = rng.randint(1, 3)
    late_margin = rng.randint(4, 8)
    # late_wait needs hyst - late_margin - already_elapsed >= 1
    if race_hyst - late_margin < 12:
        late_margin = max(4, race_hyst - 12)
    return sweep, race_hyst, early, b2b, late_margin


class smc_dma_cg_activity_test_seq(SmcCsrSeq):
    """LIVE DMA clock-gating activity sequence for SMC_DMA_CG_ACTIVITY_TEST."""

    def __init__(self, name: str = "smc_dma_cg_activity_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    def _log_step(self, step_id: str, msg: str) -> None:
        cocotb.log.info("STEP %s: %s", step_id, msg)

    def _emit_chk(self, name: str, line: str) -> None:
        # One substantive checker → exactly one greppable evidence line.
        cocotb.log.info("%s", line)
        self.chk_seen[name] = line

    def _mark_fence(self, term: str) -> None:
        t = int(get_sim_time(units="ns"))
        self.fence.append((term, t))
        cocotb.log.info("FENCE %s @ %dns", term, t)

    def _sample_bit(self, name: str) -> int:
        handle = getattr(self._dut(), name)
        val = handle.value
        if val.is_resolvable is False:
            raise AssertionError(f"{name} sample is X/Z (unobservable)")
        return int(val)

    async def _count_gated_rising(self, smc_cycles: int) -> int:
        """Count rising edges on tb_dma_gated_clk over ~smc_cycles of clk_smc_i.

        Uses a concurrent edge counter on the gated clock itself to avoid
        same-edge sampling races against clk_smc_i.
        """
        edges = {"n": 0}
        stop = {"done": False}

        async def _edge_counter() -> None:
            while not stop["done"]:
                await RisingEdge(self._dut().tb_dma_gated_clk)
                if not stop["done"]:
                    edges["n"] += 1

        counter = cocotb.start_soon(_edge_counter())
        await ClockCycles(self._dut().clk_smc_i, smc_cycles)
        stop["done"] = True
        # Unblock the counter if it is waiting on a gated edge that never comes.
        await Timer(1, units="ps")
        counter.kill()
        return edges["n"]

    async def _wait_gated_off(self, hyst: int) -> tuple[int, int]:
        """Wait until IDLE_OBSERVE consecutive smc cycles show zero gated rising edges."""
        last_toggle_at = -1
        for cyc in range(0, GATE_OFF_TIMEOUT_SMC, IDLE_OBSERVE):
            edges = await self._count_gated_rising(IDLE_OBSERVE)
            if edges == 0 and cyc >= hyst:
                return cyc + IDLE_OBSERVE, last_toggle_at
            if edges > 0:
                last_toggle_at = cyc + IDLE_OBSERVE
        busy = self._sample_bit("tb_dma_busy")
        cg = self._sample_bit("tb_dma_cg_en")
        raise AssertionError(
            f"TIMEOUT waiting DMA gated clock off: last_toggle_at={last_toggle_at} "
            f"tb_dma_busy={busy} tb_dma_cg_en={cg} hyst={hyst}"
        )

    async def _program_cg(self, *, enable: bool, hyst: int) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~DMA_CG_EN & ~CG_HYST_MASK) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
        if enable:
            nxt |= DMA_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        want_en = DMA_CG_EN if enable else 0
        got_en = rb & DMA_CG_EN
        assert got_en == want_en, f"dma_cg_en readback {got_en} != {want_en}"
        got_h = (rb & CG_HYST_MASK) >> CG_HYST_SHIFT
        assert got_h == hyst, f"cg_hysteresis readback {got_h} != {hyst}"

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, length=8
        )

    async def _write_bytes(self, addr: int, data: bytes) -> None:
        """Frontdoor preload via 8-byte AXI beats (agent AxSIZE limit)."""
        assert self.env is not None
        assert len(data) % 8 == 0, f"preload length must be 8-byte aligned, got {len(data)}"
        for off in range(0, len(data), 8):
            chunk = data[off : off + 8]
            item_name = f"jtag_dma_cg_wr_0x{addr + off:x}"
            item = SmcSysAxiItem(item_name)
            item.op = SmcSysAxiOp.WRITE
            item.addr = addr + off
            item.length = 8
            item.wdata = int.from_bytes(chunk, "little")
            item.update_golden = True
            item.memory_region = DMA_MODEL_REGION
            await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _program_dma_descriptors(self, length: int) -> None:
        await self.csr_write("DMA_CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self.csr_write(
            "DMA_DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32)
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32)
        await self.csr_write("DMA_LENGTH_LO", DMA_CTRL_LENGTH_LO, length)
        await self.csr_write("DMA_LENGTH_HI", DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write("DMA_DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write("DMA_DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write("DMA_SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write("DMA_SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write("DMA_NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1)
        await self.csr_write("DMA_NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0)

    async def _start_dma(self) -> int:
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", DMA_CTRL_NEXT_ID_0)
        assert start_id != 0, "DMA command was not accepted"
        return start_id

    async def _wait_dma_done(self, baseline_done: int) -> None:
        for _ in range(200):
            done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
            if done > baseline_done:
                return
            await ClockCycles(self._dut().clk_smc_i, 20)
        status = await self.csr_read("DMA_STATUS_0_TIMEOUT", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"DMA did not complete: baseline_done={baseline_done} status=0x{status:x}"
        )

    async def _observe_backend_only_keep_enabled(self, window: int) -> dict:
        """Prove keep-enabled under backend-only after a free-running wake.

        S3 / CHK-DMA-WAKEUP-BACKEND:
          1) prior activity wake leaves the shared DMA clock free-running
          2) establish backend_busy=1 && frontend_busy=0
          3) gated clock toggles every cycle for the entire observed window
        Not gated-off→resume.
        """
        dut = self._dut()
        state = {
            "be_at": -1,
            "smc": 0,
            "edges_before_be": 0,
            "fe_seen": 0,
            "busy_seen": 0,
            "free_running": False,
        }
        stop_pre = {"done": False}

        async def _edge_before_be() -> None:
            while not stop_pre["done"]:
                await RisingEdge(dut.tb_dma_gated_clk)
                if not stop_pre["done"]:
                    state["edges_before_be"] += 1
                    # Multiple gated edges ⇒ free-running after activity wake.
                    if state["edges_before_be"] >= 4:
                        state["free_running"] = True

        edge_mon = cocotb.start_soon(_edge_before_be())
        # Accept backend-only only after free-running is established (and after
        # some frontend/busy activity), so startup be=1&fe=0 glitches cannot
        # stand in for keep-enabled under a free-running clock.
        for cyc in range(BACKEND_ONLY_TIMEOUT_SMC):
            await RisingEdge(dut.clk_smc_i)
            state["smc"] = cyc + 1
            fe = self._sample_bit("tb_dma_frontend_busy")
            be = self._sample_bit("tb_dma_backend_busy")
            busy = self._sample_bit("tb_dma_busy")
            if fe == 1:
                state["fe_seen"] = 1
            if busy == 1:
                state["busy_seen"] = 1
            if (
                state["free_running"]
                and (state["fe_seen"] or state["busy_seen"])
                and be == 1
                and fe == 0
            ):
                state["be_at"] = state["smc"]
                break
        stop_pre["done"] = True
        await Timer(1, units="ps")
        edge_mon.kill()

        if state["be_at"] < 0:
            fe = self._sample_bit("tb_dma_frontend_busy")
            be = self._sample_bit("tb_dma_backend_busy")
            raise AssertionError(
                f"TIMEOUT waiting backend-only keep-enabled window: "
                f"frontend_busy={fe} backend_busy={be} "
                f"edges_before={state['edges_before_be']} "
                f"free_running={state['free_running']} "
                f"fe_seen={state['fe_seen']} busy_seen={state['busy_seen']}"
            )

        # Observe the entire backend-only window. Per-cycle: sample busy pair on
        # each smc edge, and require a gated rising within that same smc period
        # (keep-enabled / every-cycle — not a bulk counter that can lose the
        # last edge to phase alignment).
        edges = 0
        fe_seen = 0
        be_min = 1
        for cyc in range(window):
            saw = {"v": False}

            async def _one_gated_rise() -> None:
                await RisingEdge(dut.tb_dma_gated_clk)
                saw["v"] = True

            watcher = cocotb.start_soon(_one_gated_rise())
            await RisingEdge(dut.clk_smc_i)
            fe = self._sample_bit("tb_dma_frontend_busy")
            be = self._sample_bit("tb_dma_backend_busy")
            fe_seen |= fe
            be_min &= be
            # Same-edge alignment: gated rise may land with this smc edge.
            if not saw["v"]:
                await Timer(1, unit="ps")
            watcher.kill()
            if not saw["v"]:
                raise AssertionError(
                    f"missing toggle on DMA gated clock during backend-only "
                    f"window at cycle {cyc}: edges_so_far={edges} window={window}"
                )
            edges += 1

        if fe_seen != 0:
            raise AssertionError(
                f"frontend_busy asserted during claimed backend-only window "
                f"(fe_seen={fe_seen} window={window})"
            )
        if be_min != 1:
            raise AssertionError(
                f"backend_busy dropped during claimed backend-only window "
                f"(be_min={be_min} window={window})"
            )
        if edges != window:
            raise AssertionError(
                f"incomplete every-cycle observation during backend-only window: "
                f"edges={edges} window={window}"
            )

        return {
            "be_at": state["be_at"],
            "edges": edges,
            "window": window,
            "edges_before_be": state["edges_before_be"],
            "fe_seen_before": state["fe_seen"],
            "frontend_busy": 0,
            "backend_busy": 1,
        }

    # ---- P2 (SMC_CG_P2_001) helpers -----------------------------------
    # Producer for the hysteresis gater's busy_i is `dma_frontend_wakeup |
    # dma_backend_busy` (hw/ip/idma_wrapper/rtl/idma_wrapper.sv); tb_top.sv
    # exposes it verbatim as tb_dma_gater_busy ("Gater busy_i ... T0 for
    # hyst measure"). A plain status *read* pulses only the AXI-to-reg
    # bridge's busy_o (idma_frontend_wrapper.sv:169, "busy when there is an
    # inflight AXI command") -- a short, frontdoor, backend-free activity
    # pulse, never a force/deposit.

    async def _cycle_step(self) -> tuple[int, bool]:
        """Advance exactly one clk_smc_i period.

        Returns (gater_busy_level, gated_clk_edge_seen_this_period), using the
        same same-edge-alignment technique as `_observe_backend_only_keep_enabled`.
        """
        dut = self._dut()
        saw = {"v": False}

        async def _one_rise() -> None:
            await RisingEdge(dut.tb_dma_gated_clk)
            saw["v"] = True

        watcher = cocotb.start_soon(_one_rise())
        await RisingEdge(dut.clk_smc_i)
        busy = self._sample_bit("tb_dma_gater_busy")
        if not saw["v"]:
            await Timer(1, units="ps")
        watcher.kill()
        return busy, saw["v"]

    async def _program_cg_field(self, *, enable: bool, hyst_value: int) -> int:
        """Program DMA_CG_EN / CG_HYSTERESIS via the generated field mask/shift
        (never a hand literal -- policy
        [ADDRESS-FROM-AUTHORITATIVE-MAP]). `hyst_value` may exceed the field's
        own width (e.g. 64 against the 6-bit CG_HYSTERESIS_W field); the write
        is masked through CG_HYST_MASK exactly as firmware computing the same
        register word would, so an out-of-range request truncates on the real
        register rather than being special-cased here. Returns the resulting
        stored field value (post-truncation), independent of the DUT's own
        clock-enable trace.
        """
        cur = await self.csr_read("P2_CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        shifted = (hyst_value << CG_HYST_SHIFT) & CG_HYST_MASK
        nxt = (cur & ~DMA_CG_EN & ~CG_HYST_MASK) | shifted
        if enable:
            nxt |= DMA_CG_EN
        await self.csr_write("P2_CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("P2_CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        want_en = DMA_CG_EN if enable else 0
        got_en = rb & DMA_CG_EN
        assert got_en == want_en, f"dma_cg_en readback {got_en} != {want_en}"
        stored = (rb & CG_HYST_MASK) >> CG_HYST_SHIFT
        expected_stored = shifted >> CG_HYST_SHIFT
        assert stored == expected_stored, (
            f"cg_hysteresis readback {stored} != expected truncated value "
            f"{expected_stored} (requested {hyst_value})"
        )
        return stored

    async def _p2_settle_idle(self, bound: int, need_idle: int = 8) -> None:
        """Bounded wait for a clean idle+gated baseline (TIMEOUT-MUST-FAIL:
        finite bound, fails with last-state diagnostic on expiry)."""
        consecutive = 0
        for _ in range(bound):
            busy, edge = await self._cycle_step()
            if edge or busy:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive >= need_idle:
                    return
        busy = self._sample_bit("tb_dma_gater_busy")
        raise AssertionError(
            f"P2 settle: DUT did not reach idle+gated within {bound} cycles "
            f"(last gater_busy={busy})"
        )

    async def _scan_activity_and_gate(
        self, trigger_coro, max_cycles: int, trail_margin: int
    ) -> list[tuple[int, int]]:
        """Run one frontdoor activity pulse concurrently while sampling
        (busy, gated_edge) every clk_smc_i period, for up to `max_cycles`
        periods, stopping once the pulse has completed and at least
        `trail_margin` extra periods have been observed (enough room to see
        the countdown expire). TIMEOUT-MUST-FAIL: bounded, fails with the
        tail of the observed timeline on expiry."""
        task = cocotb.start_soon(trigger_coro)
        timeline: list[tuple[int, int]] = []
        trailing = 0
        for _ in range(max_cycles):
            busy, edge = await self._cycle_step()
            timeline.append((busy, int(edge)))
            if task.done():
                trailing += 1
                if trailing >= trail_margin:
                    break
        if not task.done():
            raise AssertionError(
                f"activity pulse task did not complete within {max_cycles} cycles "
                f"(timeline_tail={timeline[-10:]})"
            )
        return timeline

    def _find_last_deassert(
        self, timeline: list[tuple[int, int]], start_idx: int, label: str
    ) -> int:
        result = None
        for i in range(start_idx, len(timeline) - 1):
            if timeline[i][0] == 1 and timeline[i + 1][0] == 0:
                result = i + 1
        if result is None:
            raise AssertionError(
                f"{label}: no activity (busy) de-assert edge found from index "
                f"{start_idx} (timeline_tail={timeline[start_idx:][-10:]})"
            )
        return result

    def _count_consecutive_edges(
        self, timeline: list[tuple[int, int]], start_idx: int, label: str
    ) -> int:
        observed = 0
        for i in range(start_idx, len(timeline)):
            if timeline[i][1] == 1:
                observed += 1
            else:
                return observed
        raise AssertionError(
            f"{label}: gated clock never deasserted within the recorded window "
            f"(start={start_idx} window={len(timeline) - start_idx} "
            f"observed_so_far={observed})"
        )

    def _assert_no_glitch(
        self, timeline: list[tuple[int, int]], start_idx: int, end_idx: int, label: str
    ) -> None:
        for i in range(start_idx, end_idx):
            busy, edge = timeline[i]
            if not edge:
                raise AssertionError(
                    f"{label}: missing gated-clock edge at timeline index {i} "
                    f"(busy={busy}) -- clock-enable glitched during the race window"
                )

    async def _race_trial(
        self,
        hyst_value: int,
        *,
        early_offset: int = P2_RACE_EARLY_OFFSET_DEFAULT,
        b2b_offset: int = P2_RACE_B2B_OFFSET_DEFAULT,
        late_margin: int = P2_RACE_LATE_MARGIN_DEFAULT,
    ) -> dict:
        """Activity-reassert race (SMC-CG-DMA-HYST.S2): reassert early in the
        countdown, back-to-back with that reassertion's own clear, then again
        just before expiry -- proving zero glitch throughout, and that the
        final, uninterrupted countdown restarts from the full window."""
        timeline: list[tuple[int, int]] = []

        async def _cycle() -> None:
            busy, edge = await self._cycle_step()
            timeline.append((busy, int(edge)))

        async def _run_pulse(label: str, margin: int = 3, bound: int = P2_RACE_PULSE_BOUND) -> None:
            task = cocotb.start_soon(self.csr_read(label, DMA_CTRL_STATUS_0))
            waited = 0
            while not task.done():
                if waited >= bound:
                    raise AssertionError(
                        f"{label}: CSR activity pulse did not complete within {bound} cycles"
                    )
                await _cycle()
                waited += 1
            for _ in range(margin):
                await _cycle()

        await _run_pulse("P2_RACE_TRIGGER_1_INIT")
        t1 = self._find_last_deassert(timeline, 0, "race-init")

        for _ in range(early_offset):
            await _cycle()
        self._assert_no_glitch(timeline, t1, len(timeline), "race-pre-early-reassert")
        early_offset_actual = len(timeline) - t1

        await _run_pulse("P2_RACE_TRIGGER_2_EARLY")
        t2 = self._find_last_deassert(timeline, t1, "race-early-reassert-clear")

        for _ in range(b2b_offset):
            await _cycle()
        self._assert_no_glitch(timeline, t2, len(timeline), "race-pre-back-to-back")
        b2b_gap_actual = len(timeline) - t2

        await _run_pulse("P2_RACE_TRIGGER_3_B2B")
        t3 = self._find_last_deassert(timeline, t2, "race-back-to-back-clear")

        # `_run_pulse`'s own trailing settle margin already advances the
        # timeline a few cycles past t3 before we get here; account for that
        # so the total wait from t3 lands at (hyst_value - LATE_MARGIN), not
        # (already_elapsed + LATE_MARGIN) cycles past it.
        already_elapsed = len(timeline) - t3
        late_wait = hyst_value - late_margin - already_elapsed
        assert late_wait >= 1, (
            f"race hyst {hyst_value} too small for late margin "
            f"{late_margin} + already-elapsed {already_elapsed}"
        )
        for _ in range(late_wait):
            await _cycle()
        self._assert_no_glitch(timeline, t3, len(timeline), "race-pre-late-reassert")
        late_offset_actual = len(timeline) - t3
        assert 0 < late_offset_actual < hyst_value, (
            f"late reassert offset {late_offset_actual} not inside "
            f"(0, {hyst_value}) of the countdown"
        )

        await _run_pulse("P2_RACE_TRIGGER_4_LATE")
        t4 = self._find_last_deassert(timeline, t3, "race-late-reassert-clear")

        for _ in range(hyst_value + P2_RACE_FINAL_MARGIN):
            await _cycle()
        final_countdown = self._count_consecutive_edges(
            timeline, t4, "race-final-uninterrupted-countdown"
        )

        return {
            "hyst": hyst_value,
            "early_offset": early_offset_actual,
            "b2b_gap": b2b_gap_actual,
            "late_offset": late_offset_actual,
            "final_countdown": final_countdown,
        }

    async def _p2_extension(self) -> None:
        """P2 extension (SMC_CG_P2_001), additive after the P1 flow in body():
        required-cell hysteresis sweep + seed-driven extras + reassert race."""
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        sweep_gaps, race_hyst_val, early_off, b2b_off, late_margin = _p2_seeded_knobs(seed)
        cocotb.log.info(
            "SEED: %d P2 knobs sweep=%s race_hyst=%d early=%d b2b=%d late_margin=%d",
            seed,
            sweep_gaps,
            race_hyst_val,
            early_off,
            b2b_off,
            late_margin,
        )

        self._log_step(
            "P2-S1",
            "SETUP: re-enable DMA clock gating and confirm idle baseline (no "
            "frontend wakeup, no backend busy, hysteresis counter settling to "
            "0) before the P2 hysteresis sweep",
        )
        self._mark_fence("SETUP")
        await self._program_cg_field(enable=True, hyst_value=0)
        await self._p2_settle_idle(P2_SETTLE_TIMEOUT_SMC)
        assert self._sample_bit("tb_dma_frontend_busy") == 0
        assert self._sample_bit("tb_dma_backend_busy") == 0
        assert self._sample_bit("tb_dma_gater_busy") == 0
        self._mark_fence("ACTIVITY-BASELINE")

        self._log_step(
            "P2-S2",
            "ACTION/RESPONSE/EFFECT for SMC-CG-DMA-HYST.S1: sweep the "
            f"programmed hysteresis over {sweep_gaps} clk_smc_i cycles "
            f"(required={P2_REQUIRED_SWEEP_GAPS} + seed extras)",
        )
        sweep_results: dict[int, tuple[int, int]] = {}
        for gap in sweep_gaps:
            actual_hyst = await self._program_cg_field(enable=True, hyst_value=gap)
            timeline = await self._scan_activity_and_gate(
                self.csr_read(f"P2_HYST_SWEEP_GAP_{gap}", DMA_CTRL_STATUS_0),
                max_cycles=P2_SWEEP_MAX_CYCLES,
                trail_margin=P2_SWEEP_TRAIL_MARGIN,
            )
            label = f"gap={gap}(hyst_field={actual_hyst})"
            t0 = self._find_last_deassert(timeline, 0, label)
            observed = self._count_consecutive_edges(timeline, t0, label)
            # One exact expectation for every gap, over-max included:
            # CG_HYSTERESIS is a 6-bit field, so gap=64 truncates to
            # `actual_hyst == 0` and `observed <= 63` could not be violated by
            # any RTL. The truncated value IS the expectation, so a wrap or a
            # clamp defect fails this cell ([NO-ALWAYS-PASS-CHECKER]).
            assert observed == actual_hyst, (
                f"{label}: expected clock-enable deassert exactly "
                f"{actual_hyst} cycles after the last activity de-assert, "
                f"observed {observed}"
                + (
                    f" (programmed gap {gap} truncates to {actual_hyst} in the "
                    f"6-bit CG_HYSTERESIS field)"
                    if gap > 63
                    else ""
                )
            )
            # Recorded ONLY after the exact compare passed above.
            sweep_results[gap] = (actual_hyst, observed)
        missing_required = [g for g in P2_REQUIRED_SWEEP_GAPS if g not in sweep_results]
        assert not missing_required, f"sweep required cells not observed: {missing_required}"
        # Coverage artifact books the required_cells, and books a cell only
        # from a measurement that passed its exact compare -- not from a
        # restatement of the required list. The 0..8 band is swept above but
        # excluded from the booking per P2_LOW_BAND_EXCLUSION_REASON.
        cells_hit = [f"hyst-gap={g}" for g in P2_REQUIRED_SWEEP_GAPS if g in sweep_results]
        cell_measurements = {
            f"hyst-gap={g}": {
                "programmed_gap": g,
                "hyst_field": sweep_results[g][0],
                "observed_deassert_cycle": sweep_results[g][1],
            }
            for g in sweep_results
        }
        cov_path = _emit_p2_hyst_sweep_coverage_report(cells_hit, cell_measurements)
        self._emit_chk(
            "CHK-DMA-HYST-SWEEP",
            "CHK-DMA-HYST-SWEEP: "
            + " ".join(
                f"gap{g}(hyst_field={sweep_results[g][0]},deassert_cyc={sweep_results[g][1]})"
                for g in sweep_gaps
            )
            + f" coverage_artifact={cov_path.name} cells={','.join(cells_hit)}"
            + " excluded="
            + ",".join(f"hyst-gap={g}" for g in P2_LOW_BAND_SWEEP_GAPS)
            + f" seed={seed}",
        )
        self._mark_fence(f"SWEEP-COMPLETE({len(cells_hit)}-cells)")

        self._log_step(
            "P2-S3",
            "ACTION/RESPONSE/EFFECT for SMC-CG-DMA-HYST.S2: activity-reassert "
            "race (early-in-countdown, back-to-back, last-cycle-before-expiry)",
        )
        race_hyst = await self._program_cg_field(enable=True, hyst_value=race_hyst_val)
        await self._p2_settle_idle(P2_SETTLE_TIMEOUT_SMC)
        race = await self._race_trial(
            race_hyst,
            early_offset=early_off,
            b2b_offset=b2b_off,
            late_margin=late_margin,
        )
        assert race["final_countdown"] == race_hyst, (
            "post-clear countdown did not restart from the full window: "
            f"expected {race_hyst}, observed {race['final_countdown']}"
        )
        self._emit_chk(
            "CHK-DMA-HYST-RACE",
            "CHK-DMA-HYST-RACE: zero_glitches=1 hyst={} early_offset={} "
            "b2b_gap={} late_offset={} final_countdown_restarted_full={}".format(
                race["hyst"],
                race["early_offset"],
                race["b2b_gap"],
                race["late_offset"],
                race["final_countdown"],
            ),
        )
        self._mark_fence("RACE-REASSERT-EARLY")
        self._mark_fence("RACE-REASSERT-LAST")

        self._log_step(
            "P2-S4",
            "TIMEOUT: every bounded wait above has a finite bound, "
            "a fail-on-expiry path, and a last-state diagnostic",
        )
        self._emit_chk(
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: sweep_bound_smc_cycles={} settle_bound_smc_cycles={} "
            "race_pulse_bound_smc_cycles={} race_final_bound_smc_cycles={} "
            "expired=0 last_gater_busy={} dma_cg_en={}".format(
                P2_SWEEP_MAX_CYCLES,
                P2_SETTLE_TIMEOUT_SMC,
                P2_RACE_PULSE_BOUND,
                race_hyst + P2_RACE_FINAL_MARGIN,
                self._sample_bit("tb_dma_gater_busy"),
                self._sample_bit("tb_dma_cg_en"),
            ),
        )

        # OBSERVED side: the cells actually booked by the sweep, each appended
        # only after its exact deassert-cycle compare passed. EXPECTED side:
        # the independent literal P2_GRADED_CELL_NAMES. The two are never
        # derived from each other, so this compare is not equal by
        # construction ([NO-ALWAYS-PASS-CHECKER]).
        sweep_fence = f"SWEEP-COMPLETE({len(cells_hit)}-cells)"
        assert cells_hit == list(P2_GRADED_CELL_NAMES), (
            f"P2 sweep booked {cells_hit}, expected exactly "
            f"{list(P2_GRADED_CELL_NAMES)} (independent literal, not derived "
            f"from P2_REQUIRED_SWEEP_GAPS or from cells_hit)"
        )
        fence_terms = [t for t, _ in self.fence[-5:]]
        expected_p2_pre_pass = [
            "SETUP",
            "ACTIVITY-BASELINE",
            # Literal-derived count, so the emitted fence term (built from
            # len(cells_hit) in `sweep_fence`) is compared against a number this
            # sequence states independently of what it booked.
            f"SWEEP-COMPLETE({len(P2_GRADED_CELL_NAMES)}-cells)",
            "RACE-REASSERT-EARLY",
            "RACE-REASSERT-LAST",
        ]
        assert fence_terms == expected_p2_pre_pass, f"P2 NONVAC fence order wrong: {fence_terms}"
        # The token is written under the SAME name the testcase gate requires
        # (`CHK-NONVAC-P2`), so each required name resolves to exactly one
        # greppable line in the kept log and the P1 and P2 fences do not share a
        # spelling ([EVIDENCE-TOKEN-CONDITIONAL]).
        p2_nonvac_line = (
            f"CHK-NONVAC-P2: SETUP < ACTIVITY-BASELINE < {sweep_fence} < "
            "RACE-REASSERT-EARLY < RACE-REASSERT-LAST < PASS"
        )
        cocotb.log.info("%s", p2_nonvac_line)
        self.chk_seen["CHK-NONVAC-P2"] = p2_nonvac_line
        self._mark_fence("PASS")
        cocotb.log.info("smc_dma_cg_activity_test_seq P2 extension PASS")

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_dma_cg_en",
            "tb_dma_gated_clk",
            "tb_dma_busy",
            "tb_dma_frontend_busy",
            "tb_dma_backend_busy",
            "tb_dma_gater_busy",
        ):
            assert hasattr(dut, port), f"missing TB observation port {port}"

        if DMA_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DMA_MODEL_REGION, DMA_SRC_ADDR, DMA_MODEL_SIZE)

        await self._program_output_fabric_pass_all()
        # Prefill both S2 and S3 source/dest buffers.
        await self._write_bytes(DMA_SRC_ADDR, DMA_PAYLOAD_S3)
        await self._write_bytes(DMA_DST_ADDR, bytes(0x5A for _ in range(len(DMA_PAYLOAD_S3))))

        # ---- S1: gate-off while idle, cg enabled ----
        self._log_step("S1", "enable dma_cg_en, idle, observe shared DMA clock gates off")
        await self._program_cg(enable=True, hyst=HYST_CYCLES)
        assert self._sample_bit("tb_dma_cg_en") == 1
        quiet_at, last_toggle = await self._wait_gated_off(HYST_CYCLES)
        edges = await self._count_gated_rising(IDLE_OBSERVE)
        assert edges == 0, f"idle window still toggling: edges={edges}"
        # last_toggle == -1 means no toggle after enable (already gated); OK.
        if last_toggle >= 0:
            assert last_toggle <= (HYST_CYCLES + IDLE_OBSERVE), (
                f"last toggle not within hyst window: last_toggle={last_toggle} "
                f"quiet_at={quiet_at} hyst={HYST_CYCLES}"
            )
        # Carry the measured last_toggle, not the bound it was compared against;
        # -1 means the clock was already gated when CG was enabled.
        self._emit_chk(
            "CHK-DMA-GATE-OFF",
            f"CHK-DMA-GATE-OFF: last_toggle_within_hyst={last_toggle} "
            f"zero_toggles_idle={IDLE_OBSERVE} quiet_at={quiet_at}",
        )
        self._mark_fence("gate-off-observed")

        # ---- S2: frontend wakeup via DMA start ----
        self._log_step("S2", "start DMA (frontend activity) and observe clock resume")
        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)
        await self._program_dma_descriptors(len(DMA_PAYLOAD_S2))
        # Descriptors may wake the gater; re-settle so NEXT_ID is the wakeup edge.
        await self._wait_gated_off(HYST_CYCLES)

        # Concurrent: wait for first gated rising after start; also track busy.
        state = {"busy_at": -1, "resume_at": -1, "smc": 0}

        async def _monitor_frontend_resume() -> None:
            while state["resume_at"] < 0 and state["smc"] < RESUME_TIMEOUT_SMC * 8:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                if state["busy_at"] < 0 and (
                    self._sample_bit("tb_dma_frontend_busy") == 1
                    or self._sample_bit("tb_dma_busy") == 1
                ):
                    state["busy_at"] = state["smc"]

        async def _watch_gated_rise() -> None:
            await RisingEdge(dut.tb_dma_gated_clk)
            state["resume_at"] = state["smc"]

        mon = cocotb.start_soon(_monitor_frontend_resume())
        rise = cocotb.start_soon(_watch_gated_rise())
        start_task_id = await self._start_dma()
        # Wait until resume seen or timeout.
        for _ in range(RESUME_TIMEOUT_SMC * 8):
            if state["resume_at"] >= 0 and state["busy_at"] >= 0:
                break
            await RisingEdge(dut.clk_smc_i)
        mon.kill()
        rise.kill()
        assert state["busy_at"] >= 0, "frontend/busy wakeup never observed after DMA start"
        assert state["resume_at"] >= 0, "gated clock did not resume after frontend wakeup"
        resume_after_busy = max(0, state["resume_at"] - state["busy_at"])
        assert resume_after_busy <= 1, (
            f"resume not within 1 cycle of frontend wakeup: delta={resume_after_busy}"
        )
        # Free-running claim, graded at the same strength as the other three
        # activity windows in this testcase (`edges == 0` over 16 idle cycles,
        # per-cycle over the backend-only window, `>= IDLE_OBSERVE - 1` with
        # gating disabled). One edge of slack covers clk_smc_i/gated-clk phase
        # alignment at the window boundary; anything looser -- `>= 2 of 4` --
        # is also satisfied by a clock resuming at half rate or re-gating inside
        # the window, which is not what this token claims ([EXACT-EXPECTATION]).
        wakeup_window = 4
        edges = await self._count_gated_rising(wakeup_window)
        assert edges >= wakeup_window - 1, (
            f"clock not continuously toggling after frontend wakeup: "
            f"{edges} rising edge(s) in a {wakeup_window}-cycle window"
        )
        self._emit_chk(
            "CHK-DMA-WAKEUP-FRONTEND",
            f"CHK-DMA-WAKEUP-FRONTEND: resume_cyc={resume_after_busy} "
            f"(bound 1) then edges={edges}/{wakeup_window} free-running "
            f"start_id={start_task_id}",
        )
        self._mark_fence("frontend-wakeup-observed")
        await self._wait_dma_done(baseline_done)

        # ---- S3: keep-enabled under backend-only ----
        # After a prior activity wake leaves the shared DMA clock free-running,
        # establish backend_busy=1 && frontend_busy=0 and prove the gated clock
        # toggles every cycle for the entire observed window.
        # Do NOT re-settle to gated-off or measure gated-off→resume.
        self._log_step(
            "S3",
            "gating enabled; after activity wake free-running, observe backend-only "
            "keep-enabled (every-cycle toggles for entire window)",
        )
        assert self._sample_bit("tb_dma_cg_en") == 1, "S3: dma_cg_en unexpectedly 0"
        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE2", DMA_CTRL_DONE_0)
        await self._program_dma_descriptors(len(DMA_PAYLOAD_S3))
        # START is the prior activity wake that leaves the shared clock free-running.
        # Do not wait for gated-off before START.
        await self._start_dma()
        obs = await self._observe_backend_only_keep_enabled(S3_MEASURE_WINDOW)
        self._emit_chk(
            "CHK-DMA-WAKEUP-BACKEND",
            "CHK-DMA-WAKEUP-BACKEND: during a backend-only window "
            "(backend_busy=1 && frontend_busy=0), the shared DMA clock toggles "
            f"every cycle for the entire observed window "
            f"(edges={obs['edges']} window={obs['window']} "
            f"edges_before_be={obs['edges_before_be']} be_at={obs['be_at']})",
        )
        self._mark_fence("backend-only-keep-enabled-observed")
        await self._wait_dma_done(baseline_done)

        # ---- S4: gating disabled keeps clock continuous while idle ----
        self._log_step("S4", "deassert dma_cg_en; idle clock stays continuously enabled")
        await self._program_cg(enable=False, hyst=HYST_CYCLES)
        assert self._sample_bit("tb_dma_cg_en") == 0
        await ClockCycles(dut.clk_smc_i, HYST_CYCLES + 4)
        edges = await self._count_gated_rising(IDLE_OBSERVE)
        # Continuously enabled ⇒ nearly every smc cycle produces a gated rising edge.
        assert edges >= (IDLE_OBSERVE - 1), (
            f"gated intervals while cg disabled: edges={edges} window={IDLE_OBSERVE}"
        )
        self._emit_chk(
            "CHK-DMA-GATING-DISABLED",
            f"CHK-DMA-GATING-DISABLED: toggles_every_cycle=1 edges={edges} window={IDLE_OBSERVE}",
        )
        self._mark_fence("gating-disabled-observed")

        # ---- CHK-NONVAC ordered fence ----
        order = [t for t, _ in self.fence]
        expected = [
            "gate-off-observed",
            "frontend-wakeup-observed",
            "backend-only-keep-enabled-observed",
            "gating-disabled-observed",
        ]
        assert order == expected, f"NONVAC fence order wrong: {order}"
        self._emit_chk(
            "CHK-NONVAC",
            "CHK-NONVAC: gate-off-observed < frontend-wakeup-observed < "
            "backend-only-keep-enabled-observed < gating-disabled-observed < PASS",
        )
        self._mark_fence("PASS")
        cocotb.log.info("smc_dma_cg_activity_test_seq PASS")

        # ---- P2 (SMC_CG_P2_001) extension ----
        await self._p2_extension()
