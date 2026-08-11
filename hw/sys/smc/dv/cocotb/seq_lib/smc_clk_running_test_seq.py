# SPDX-License-Identifier: Apache-2.0
"""
DV-CARD: SMCCGP0_001 ANCHOR: smc_clk_running_test
DV-CARD-REVISION: 1 RECORD-SHA256: c9a8f2011802914da1e11a25c66a37abbfcfed17058830392c07cfd14228c33c
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_P0_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
# Also preserves P1 evidence tokens CHK-ACTIVE-RUNNING / legacy fence for closed P1 grade.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq
from . import smc_cg_obs_utils as cg
from . import smc_addr_map as _addr

_LOG = cocotb.log

HYST_CYCLES = 8
ACTIVE_WINDOW = 16
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256
RESUME_TIMEOUT_SMC = 64
DMA_DONE_TIMEOUT_SMC = 2048

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
DMA_MODEL_REGION = "clk_running_dma_fabric"
DMA_MODEL_SIZE = 0x1000
# Short beat + many repetitions keep DMA busy across the concurrent window.
DMA_PAYLOAD = bytes.fromhex("A1B2C3D4E5F60708")
DMA_REPS = 32


class smc_clk_running_test_seq(SmcCsrSeq):
    """P0 bring-up LIVE: CG enable readback, idle gated baseline, DMA activity ungate.

    Also emits legacy P1 CHK-ACTIVE-RUNNING for the closed P1 grade on this anchor.
    """

    def __init__(self, name: str = "smc_clk_running_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(
        self, *, dma_en: bool, zeroer_en: bool, hyst: int
    ) -> int:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (
            cur
            & ~DMA_CG_EN
            & ~ZEROER_CG_EN
            & ~CG_HYST_MASK
        ) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
        if dma_en:
            nxt |= DMA_CG_EN
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)
        rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, length=8)
        assert (rb & DMA_CG_EN) == (DMA_CG_EN if dma_en else 0)
        assert (rb & ZEROER_CG_EN) == (ZEROER_CG_EN if zeroer_en else 0)
        assert ((rb & CG_HYST_MASK) >> CG_HYST_SHIFT) == hyst
        return rb

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
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
        item_name = f"jtag_clk_run_wr_0x{addr:x}"
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
        await self.csr_write(
            "DMA_DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32
        )
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write(
            "DMA_SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32
        )
        await self.csr_write("DMA_LENGTH_LO", DMA_CTRL_LENGTH_LO, len(DMA_PAYLOAD))
        await self.csr_write("DMA_LENGTH_HI", DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write("DMA_DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write("DMA_DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write("DMA_SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write("DMA_SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write(
            "DMA_NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, DMA_REPS
        )
        await self.csr_write("DMA_NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0)

    async def _start_dma(self) -> int:
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", DMA_CTRL_NEXT_ID_0)
        assert start_id != 0, "DMA command was not accepted"
        return start_id

    async def _wait_dma_busy(self) -> None:
        dut = self._dut()
        for _ in range(RESUME_TIMEOUT_SMC * 8):
            if (
                cg.sample_bit(dut, "tb_dma_busy") == 1
                or cg.sample_bit(dut, "tb_dma_frontend_busy") == 1
                or cg.sample_bit(dut, "tb_dma_backend_busy") == 1
            ):
                return
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            "TIMEOUT waiting DMA busy: "
            f"busy={cg.sample_bit(dut, 'tb_dma_busy')} "
            f"fe={cg.sample_bit(dut, 'tb_dma_frontend_busy')} "
            f"be={cg.sample_bit(dut, 'tb_dma_backend_busy')}"
        )

    async def _wait_dma_done(self, baseline_done: int) -> int:
        """Bounded DMA-completion wait; fail-on-expiry with last state."""
        dut = self._dut()
        bound = DMA_DONE_TIMEOUT_SMC
        last_done = baseline_done
        for cyc in range(bound):
            last_done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
            if last_done != baseline_done:
                return cyc
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(
            f"TIMEOUT DMA completion: bound_smc_cycles={bound} expired=1 "
            f"last_state done={last_done:#x} baseline={baseline_done:#x} "
            f"busy={cg.sample_bit(dut, 'tb_dma_busy')} "
            f"fe={cg.sample_bit(dut, 'tb_dma_frontend_busy')} "
            f"be={cg.sample_bit(dut, 'tb_dma_backend_busy')}"
        )

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_dma_cg_en",
            "tb_dma_gated_clk",
            "tb_dma_busy",
            "tb_zeroer_cg_en",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_busy",
        ):
            assert hasattr(dut, port), f"missing TB observation port {port}"

        if DMA_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(DMA_MODEL_REGION, DMA_SRC_ADDR, DMA_MODEL_SIZE)

        await self._program_output_fabric_pass_all()
        await self._write_bytes(DMA_SRC_ADDR, DMA_PAYLOAD)
        await self._write_bytes(
            DMA_DST_ADDR, bytes(0x5A for _ in range(len(DMA_PAYLOAD)))
        )

        # ---- S1: CG enable frontdoor write + readback ----
        cg.log_step(
            "S1",
            "frontdoor-write CLOCK_GATE_CONTROL DMA_CG_EN=1 ZEROER_CG_EN=1; readback",
        )
        rb = await self._program_cg(dma_en=True, zeroer_en=True, hyst=HYST_CYCLES)
        assert cg.sample_bit(dut, "tb_dma_cg_en") == 1
        assert cg.sample_bit(dut, "tb_zeroer_cg_en") == 1
        dma_rb = int((rb & DMA_CG_EN) != 0)
        zeroer_rb = int((rb & ZEROER_CG_EN) != 0)
        cg.emit_chk(
            self.chk_seen,
            "CHK-CG-ENABLE-READBACK",
            "CHK-CG-ENABLE-READBACK: DMA_CG_EN=1 ZEROER_CG_EN=1 "
            f"readback_dma={dma_rb} readback_zeroer={zeroer_rb} match=1",
        )
        cg.mark_fence(self.fence, "cg-enable-readback")

        # ---- S2: idle gated baseline (no DMA programmed yet) ----
        cg.log_step(
            "S2",
            "gating enabled, no DMA descriptor; sample dma + zeroer axi idle-gated",
        )
        await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=0,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_busy", "tb_zeroer_cg_en"),
        )
        await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST_CYCLES,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_busy", "tb_dma_cg_en"),
        )
        dma_idle, zaxi_idle = await cg.count_enabled_pair_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            IDLE_OBSERVE,
        )
        assert dma_idle == 0, f"idle DMA clock still toggling: edges={dma_idle}"
        assert zaxi_idle == 0, f"idle Zeroer axi_clk still toggling: edges={zaxi_idle}"
        cg.emit_chk(
            self.chk_seen,
            "CHK-IDLE-GATED-BASELINE",
            "CHK-IDLE-GATED-BASELINE: "
            f"dma_toggle_count={dma_idle} zeroer_axi_toggle_count={zaxi_idle} "
            f"window={IDLE_OBSERVE}",
        )
        cg.mark_fence(self.fence, "idle-gated-baseline")

        # ---- S3: one DMA transfer; dma ungates; zeroer stays idle ----
        cg.log_step(
            "S3",
            "program/trigger one DMA transfer; sample dma ungate + zeroer idle",
        )
        await self._program_dma_descriptors()
        # Descriptor CSR writes may wake DMA; re-settle then start.
        await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST_CYCLES,
            idle_observe=IDLE_OBSERVE,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_busy", "tb_dma_cg_en"),
        )
        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)
        await self._start_dma()
        await self._wait_dma_busy()

        dma_edges, zaxi_edges = await cg.count_enabled_pair_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            ACTIVE_WINDOW,
        )
        assert dma_edges == ACTIVE_WINDOW, (
            f"active DMA clock missing toggles: edges={dma_edges} "
            f"window={ACTIVE_WINDOW}"
        )
        assert zaxi_edges == 0, (
            f"idle Zeroer axi_clk still toggling during DMA: edges={zaxi_edges}"
        )
        assert cg.sample_bit(dut, "tb_zeroer_busy") == 0, "Zeroer unexpectedly busy"
        toggles_every = int(dma_edges == ACTIVE_WINDOW)
        axi_gated = int(zaxi_edges == 0)
        cg.emit_chk(
            self.chk_seen,
            "CHK-DMA-ACTIVITY-UNGATE",
            "CHK-DMA-ACTIVITY-UNGATE: "
            f"toggles_every_cycle={toggles_every} dma_edges={dma_edges} "
            f"window={ACTIVE_WINDOW} zeroer_axi_edges={zaxi_edges}",
        )
        # Legacy P1 token (closed P1 grade still greps this name).
        cg.emit_chk(
            self.chk_seen,
            "CHK-ACTIVE-RUNNING",
            "CHK-ACTIVE-RUNNING: active_module=DMA "
            f"toggles_every_cycle={toggles_every} dma_edges={dma_edges} "
            f"idle_module=Zeroer axi_clk_gated={axi_gated} "
            f"zeroer_edges={zaxi_edges} concurrent_window={ACTIVE_WINDOW}",
        )
        cg.mark_fence(self.fence, "dma-activity-ungate")

        # ---- S4: bounded DMA completion wait ----
        cg.log_step("S4", "bounded wait for DMA transfer completion")
        done_cyc = await self._wait_dma_done(baseline_done)
        cg.emit_chk(
            self.chk_seen,
            "CHK-TIMEOUT-PATHS",
            "CHK-TIMEOUT-PATHS: "
            f"bound_smc_cycles={DMA_DONE_TIMEOUT_SMC} expired=0 "
            f"done_after_smc={done_cyc} fail_on_expiry=1",
        )

        cg.assert_fence_order(
            self.fence,
            [
                "cg-enable-readback",
                "idle-gated-baseline",
                "dma-activity-ungate",
            ],
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: cg-enable-readback < idle-gated-baseline < "
            "dma-activity-ungate < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_clk_running_test_seq PASS")
