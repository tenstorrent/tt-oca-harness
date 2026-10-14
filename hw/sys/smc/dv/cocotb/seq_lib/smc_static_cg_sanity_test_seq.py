# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_002 ANCHOR: smc_static_cg_sanity_test
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# Every record this sequence emits goes through `cocotb.log`: a module-level
# `logging.getLogger(__name__)` is not captured by the cocotb/pyuvm runner, so
# the STEP/CHK/FENCE evidence written through one never reaches the kept log
# ([EVIDENCE-TOKEN-CONDITIONAL]).

# Enable threshold and hysteresis control are the same programmable field.
# Lowest hysteresis whose DMA completion survives the gater with the SYS_OUT
# slave agent's one-cycle response latency; 8 and below drop the transfer
# (smc_clk_multi_window_test_seq.HYST_LOW_EXCLUSION records the band).
THRESH_MIN = 9
THRESH_MAX = 63
HYST_IDLE = 8
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 512

# Authoritative map (also re-exported via smc_cg_obs_utils).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
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

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0100
DMA_MODEL_REGION = "static_cg_dma_fabric"
DMA_MODEL_SIZE = 0x1000
DMA_PAYLOAD = bytes.fromhex("A1B2C3D4E5F60708")


class smc_static_cg_sanity_test_seq(SmcCsrSeq):
    """LIVE per-module enable/disable + enable-threshold (hyst) boundaries."""

    def __init__(self, name: str = "smc_static_cg_sanity_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}
        self.required_cells_hit: list[str] = []
        self.measured: dict[str, int] = {}
        # One entry per bounded wait this sequence actually entered:
        # (label, smc cycles the wait consumed, the bound it was given). Each
        # wait raises on expiry, so the margin recorded here is what the run
        # measured.
        self.bounded_waits: list[tuple[str, int, int]] = []

    def _dut(self):
        return cocotb.top

    async def _program_cg(self, *, dma_en: bool, zeroer_en: bool, hyst: int) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~DMA_CG_EN & ~ZEROER_CG_EN & ~CG_HYST_MASK) | (
            (hyst << CG_HYST_SHIFT) & CG_HYST_MASK
        )
        if dma_en:
            nxt |= DMA_CG_EN
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert (rb & DMA_CG_EN) == (DMA_CG_EN if dma_en else 0)
        assert (rb & ZEROER_CG_EN) == (ZEROER_CG_EN if zeroer_en else 0)
        assert ((rb & CG_HYST_MASK) >> CG_HYST_SHIFT) == hyst

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
        item_name = f"jtag_static_cg_wr_0x{addr:x}"
        item = SmcSysAxiItem(item_name)
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = len(data)
        item.wdata = int.from_bytes(data, "little")
        item.update_golden = True
        item.memory_region = DMA_MODEL_REGION
        await _OneShot(item, f"{item_name}_os").start(self.env.jtag_axi_agent.sequencer)

    async def _program_dma_descriptors(self) -> None:
        await self.csr_write("DMA_CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self.csr_write(
            "DMA_DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32)
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32)
        await self.csr_write("DMA_LENGTH_LO", DMA_CTRL_LENGTH_LO, len(DMA_PAYLOAD))
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

    async def _gate_off(self, label: str, hyst: int) -> None:
        """Bounded wait for tb_dma_gated_clk to go quiet, margin recorded."""
        dut = self._dut()
        used, _last_toggle = await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=hyst,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_gater_busy", "tb_dma_cg_en"),
        )
        self.bounded_waits.append((label, used, GATE_OFF_TIMEOUT_SMC))

    async def _wait_dma_done(self, baseline_done: int, label: str) -> None:
        dut = self._dut()
        for polls in range(1, 81):
            done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
            if done > baseline_done:
                self.bounded_waits.append((f"{label}/done-poll", polls, 80))
                for busy_cyc in range(GATE_OFF_TIMEOUT_SMC):
                    if cg.sample_bit(dut, "tb_dma_gater_busy") == 0:
                        self.bounded_waits.append(
                            (f"{label}/busy-clear", busy_cyc, GATE_OFF_TIMEOUT_SMC)
                        )
                        return
                    await RisingEdge(dut.clk_smc_i)
                raise AssertionError("TIMEOUT waiting gater busy clear after DONE")
            await ClockCycles(dut.clk_smc_i, 20)
        status = await self.csr_read("DMA_STATUS_0_TIMEOUT", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"TIMEOUT waiting DMA done: baseline={baseline_done} status=0x{status:x}"
        )

    async def _measure_threshold(self, step_id: str, hyst: int, cell: str, fence: str) -> int:
        dut = self._dut()
        cg.log_step(step_id, f"enable-threshold/hyst={hyst}; measure re-gate delay")
        await self._program_cg(dma_en=True, zeroer_en=False, hyst=hyst)
        await self._gate_off(f"{step_id}/gate-off-pre", hyst)
        baseline = await self.csr_read(f"DMA_DONE_BASE_{step_id}", DMA_CTRL_DONE_0)
        await self._program_dma_descriptors()
        await self._gate_off(f"{step_id}/gate-off-armed", hyst)

        state = {"busy_seen": False, "busy_fall_at": -1, "last_edge_at": -1, "smc": 0}
        stop = {"done": False}

        async def _meter() -> None:
            while not stop["done"]:
                await RisingEdge(dut.clk_smc_i)
                state["smc"] += 1
                busy = cg.sample_bit(dut, "tb_dma_gater_busy") == 1
                if busy:
                    state["busy_seen"] = True
                    state["busy_fall_at"] = -1
                elif state["busy_seen"] and state["busy_fall_at"] < 0:
                    state["busy_fall_at"] = state["smc"]

        async def _edge_watch() -> None:
            while not stop["done"]:
                await RisingEdge(dut.tb_dma_gated_clk)
                if not stop["done"]:
                    state["last_edge_at"] = state["smc"]

        meter = cocotb.start_soon(_meter())
        edges = cocotb.start_soon(_edge_watch())
        await self._start_dma()
        await self._wait_dma_done(baseline, step_id)
        quiet_used = 0
        for _ in range(GATE_OFF_TIMEOUT_SMC):
            quiet_used += 1
            if (
                state["busy_fall_at"] >= 0
                and state["last_edge_at"] >= state["busy_fall_at"]
                and state["smc"] - state["last_edge_at"] >= 4
            ):
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            stop["done"] = True
            meter.kill()
            edges.kill()
            raise AssertionError(
                f"TIMEOUT waiting threshold quiet {step_id}: "
                f"fall={state['busy_fall_at']} last={state['last_edge_at']} hyst={hyst}"
            )
        stop["done"] = True
        meter.kill()
        edges.kill()
        self.bounded_waits.append((f"{step_id}/threshold-quiet", quiet_used, GATE_OFF_TIMEOUT_SMC))
        assert state["busy_seen"] and state["busy_fall_at"] >= 0
        delay = max(0, state["last_edge_at"] - state["busy_fall_at"] + 1)
        assert abs(delay - hyst) <= 1, f"threshold delay {delay} != programmed {hyst} (±1)"
        self.measured[cell] = delay
        self.required_cells_hit.append(cell)
        cg.mark_fence(self.fence, fence)
        return delay

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_dma_cg_en",
            "tb_dma_gated_clk",
            "tb_dma_gater_busy",
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            "tb_zeroer_busy",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        if DMA_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DMA_MODEL_REGION, DMA_SRC_ADDR, DMA_MODEL_SIZE)
        await self._program_output_fabric_pass_all()
        await self._write_bytes(DMA_SRC_ADDR, DMA_PAYLOAD)
        await self._write_bytes(DMA_DST_ADDR, bytes(0x5A for _ in range(len(DMA_PAYLOAD))))

        # ---- P0 S1/S2: DMA gating disabled → free-run while idle ----
        cg.log_step(
            "S1",
            "CLOCK_GATE_CONTROL DMA_CG_EN=0 ZEROER_CG_EN=1; no DMA activity",
        )
        await self._program_cg(dma_en=False, zeroer_en=True, hyst=HYST_IDLE)
        assert cg.sample_bit(dut, "tb_dma_cg_en") == 0
        await ClockCycles(dut.clk_smc_i, HYST_IDLE + 4)
        cg.log_step("S2", "sample dma_gated_clk free-run with cg disabled")
        dma_edges_s1 = await cg.count_enabled_at_smc_rise(dut, "tb_dma_gated_clk", IDLE_OBSERVE)
        assert dma_edges_s1 == IDLE_OBSERVE, (
            f"DMA gated off while cg disabled: edges={dma_edges_s1} window={IDLE_OBSERVE}"
        )
        # The two enables and the busy bit are re-read off the DUT at emission
        # time, so the token reports the sampled window ([EXACT-EXPECTATION]).
        cg.emit_chk(
            self.chk_seen,
            "CHK-DMA-GATE-DISABLED-FREE-RUN",
            "CHK-DMA-GATE-DISABLED-FREE-RUN: "
            f"dma_edges={dma_edges_s1}/{IDLE_OBSERVE} "
            f"dma_cg_en={cg.sample_bit(dut, 'tb_dma_cg_en')} "
            f"zeroer_cg_en={cg.sample_bit(dut, 'tb_zeroer_cg_en')} "
            f"dma_gater_busy={cg.sample_bit(dut, 'tb_dma_gater_busy')}",
        )
        cg.mark_fence(self.fence, "dma-gate-disabled-free-run")

        # ---- P0 S3/S4: Zeroer gating disabled → axi+reg free-run ----
        cg.log_step(
            "S3",
            "CLOCK_GATE_CONTROL ZEROER_CG_EN=0 DMA_CG_EN=1; no Zeroer activity",
        )
        await self._program_cg(dma_en=True, zeroer_en=False, hyst=HYST_IDLE)
        assert cg.sample_bit(dut, "tb_dma_cg_en") == 1
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 0
        await self._gate_off("S3/gate-off", HYST_IDLE)
        cg.log_step(
            "S4",
            "sample zeroer axi_clk + reg_clk free-run with disable_cg / cg off",
        )
        dma_n, zaxi_n, zreg_n = await cg.count_enabled_triple_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        assert dma_n == 0, f"DMA should be gated: edges={dma_n}"
        assert zaxi_n == IDLE_OBSERVE, (
            f"Zeroer axi should stay enabled (cg disabled): edges={zaxi_n}"
        )
        assert zreg_n == IDLE_OBSERVE, (
            f"Zeroer reg should stay enabled (cg disabled): edges={zreg_n}"
        )
        self.required_cells_hit.extend(["module_gating_disabled", "module_gating_enabled"])
        cg.emit_chk(
            self.chk_seen,
            "CHK-ZEROER-GATE-DISABLED-FREE-RUN",
            "CHK-ZEROER-GATE-DISABLED-FREE-RUN: "
            f"zeroer_axi_edges={zaxi_n}/{IDLE_OBSERVE} "
            f"zeroer_reg_edges={zreg_n}/{IDLE_OBSERVE} "
            f"dma_edges={dma_n}/{IDLE_OBSERVE} "
            f"dma_cg_en={cg.sample_bit(dut, 'tb_dma_cg_en')} "
            f"zeroer_cg_en={cg.sample_bit(dut, 'tb_zeroer_cg_en')} "
            f"zeroer_busy={cg.sample_bit(dut, 'tb_zeroer_busy')}",
        )
        cg.mark_fence(self.fence, "zeroer-gate-disabled-free-run")
        # P1 module-gating token: the raw per-module edge counts of the two
        # windows above ([EXACT-EXPECTATION]).
        cg.emit_chk(
            self.chk_seen,
            "CHK-MODULE-GATING",
            "CHK-MODULE-GATING: disabled_module=DMA "
            f"dma_edges_s1={dma_edges_s1}/{IDLE_OBSERVE} "
            f"dma_gated_edges={dma_n}/{IDLE_OBSERVE} "
            f"zeroer_ungated_edges={zaxi_n}/{IDLE_OBSERVE}",
        )

        # ---- P1 enable-threshold (=hyst) sweep points ----
        # The cells are named after the hysteresis value each one measures.
        # CG_HYSTERESIS is a 6-bit field whose true minimum is 0; THRESH_MIN is
        # the lowest point this sequence exercises, not the field's floor, and
        # the 0..8 band is unproven.
        d_min = await self._measure_threshold(
            "S3b",
            THRESH_MIN,
            f"enable_threshold_delay_hyst{THRESH_MIN}",
            "enable-threshold-min-measured",
        )
        d_max = await self._measure_threshold(
            "S4b",
            THRESH_MAX,
            f"enable_threshold_delay_hyst{THRESH_MAX}",
            "enable-threshold-max-measured",
        )
        assert d_max >= d_min

        cg.emit_chk(
            self.chk_seen,
            "CHK-ENABLE-THRESHOLD",
            "CHK-ENABLE-THRESHOLD: re-gate delay tracks CG_HYSTERESIS within "
            f"1 cycle at the two swept points: hyst={THRESH_MIN} -> delay="
            f"{d_min}, hyst={THRESH_MAX} -> delay={d_max}. CG_HYSTERESIS 0..8 "
            f"is NOT swept here",
        )
        # Each bounded wait raises on expiry; the token reports the cycles each
        # one consumed against the bound it was given.
        worst = max(self.bounded_waits, key=lambda w: w[1] / w[2])
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            f"CHK-TIMEOUT-PATHS: {len(self.bounded_waits)} bounded waits "
            f"entered, 0 expired (expiry raises); tightest margin "
            f"{worst[0]} used {worst[1]}/{worst[2]} smc cycles; "
            f"all: {','.join(f'{n}={u}/{b}' for n, u, b in self.bounded_waits)}",
        )
        # P0 NONVAC is the contract for SMCCGP0_002; P0 fence terms lead.
        # `assert_fence_progress` requires every listed phase to have consumed
        # simulation time; order alone holds by construction in a straight-line
        # body ([NO-ALWAYS-PASS-CHECKER]). The strong content of this testcase
        # is the gated-clock edge counts and the hysteresis measurement in
        # `_measure_threshold`.
        #
        # Every term listed below is separated from its predecessor by at least
        # one multi-cycle DUT wait: a `count_enabled_at_smc_rise` window between
        # the two free-run phases, and a full program/gate-off/DMA cycle before
        # each threshold measurement. Only phases with that property belong in
        # the list; a mark placed after an `emit_chk` alone would share its
        # predecessor's timestamp and fail here.
        _PHASES = [
            "dma-gate-disabled-free-run",
            "zeroer-gate-disabled-free-run",
            "enable-threshold-min-measured",
            "enable-threshold-max-measured",
        ]
        fence_times = cg.assert_fence_progress(self.fence, _PHASES)
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: all %d phases in order with strictly increasing DUT "
            "timestamps %s ns (order alone is true by construction; the "
            "timestamps are what this leg adds). Fail-capable content of the "
            "testcase is elsewhere: the per-module gated-clock edge counts and "
            "the hysteresis measurement." % (len(_PHASES), ",".join(str(t) for t in fence_times)),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_static_cg_sanity_test_seq PASS")
