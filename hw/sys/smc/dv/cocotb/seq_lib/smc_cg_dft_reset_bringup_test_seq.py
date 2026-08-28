# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_003 ANCHOR: smc_cg_dft_reset_bringup_test
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from env.smc_reset_item import SmcResetItem, SmcResetOp

from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq
from . import smc_cg_obs_utils as cg
from . import smc_addr_map as _addr

_LOG = logging.getLogger(__name__)

HYST = 8
IDLE_OBSERVE = 16
RESET_WAIT_BOUND_SMC = 400
RESET_RECOVER_BOUND_SMC = 800

# Authoritative map (also re-exported via smc_cg_obs_utils for shared helpers).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK


class smc_cg_dft_reset_bringup_test_seq(SmcCsrSeq):
    """LIVE/CONNECTIVITY DFT test_en_i bypass (DMA+Zeroer) and Zeroer reset-override
    free-running (SMCCGP0_003, Skill 1.5)."""

    def __init__(self, name: str = "smc_cg_dft_reset_bringup_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.chk_seen: dict[str, str] = {}

    def _dut(self):
        return cocotb.top

    async def _program_cg(
        self, *, dma_en: bool, zeroer_en: bool, hyst: int = HYST
    ) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (
            cur & ~DMA_CG_EN & ~ZEROER_CG_EN & ~CG_HYST_MASK
        ) | ((hyst << CG_HYST_SHIFT) & CG_HYST_MASK)
        if dma_en:
            nxt |= DMA_CG_EN
        if zeroer_en:
            nxt |= ZEROER_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_WR", CLOCK_GATE_CONTROL, nxt, length=8)

    async def _reset_op(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await _OneShot(item, f"reset_{op.value.lower()}_os").start(
            self.env.reset_agent.sequencer
        )
        return item

    async def _reset_sample(self) -> SmcResetItem:
        item = SmcResetItem("raw_sample")
        item.op = SmcResetOp.RAW_SAMPLE
        await _OneShot(item, "reset_raw_sample_os").start(self.env.reset_agent.sequencer)
        return item

    async def _wait_reset_state(
        self, *, want_asserted: bool, bound_smc: int, label: str
    ) -> SmcResetItem:
        """Bounded poll (per SMC clock) of rst_primary_smc_clk_n via the reset
        agent's RAW_SAMPLE; fails with last-state diagnostics on expiry."""
        dut = self._dut()
        last: SmcResetItem | None = None
        want = 0 if want_asserted else 1
        for _ in range(bound_smc):
            await RisingEdge(dut.clk_smc_i)
            last = await self._reset_sample()
            if last.resolvable and last.rst_primary_smc_clk_n == want:
                return last
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound_smc} smc_cycles want_rst_primary_smc_clk_n={want} "
            f"last={last}"
        )

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_test_en_i",
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        # ---- S1: assert test_en_i; enable DMA+Zeroer gating; no module activity ----
        cg.log_step(
            "S1",
            "assert test_en_i; frontdoor CLOCK_GATE_CONTROL DMA_CG_EN=1 ZEROER_CG_EN=1; "
            "no module activity",
        )
        dut.tb_test_en_i.value = 1
        await self._program_cg(dma_en=True, zeroer_en=True)

        # ---- S2: sample all three gated clocks with test_en_i asserted ----
        cg.log_step(
            "S2",
            "sample dma_gated_clk / zeroer_axi_gated_clk / zeroer_reg_gated_clk for a fixed "
            "window with test_en_i asserted",
        )
        await ClockCycles(dut.clk_smc_i, HYST + 4)
        dma_edges, zaxi_edges, zreg_edges = await cg.count_enabled_triple_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        assert dma_edges == IDLE_OBSERVE, (
            f"DMA clock gated under test_en_i: edges={dma_edges} window={IDLE_OBSERVE}"
        )
        assert zaxi_edges == IDLE_OBSERVE, (
            f"Zeroer axi_clk gated under test_en_i: edges={zaxi_edges} window={IDLE_OBSERVE}"
        )
        assert zreg_edges == IDLE_OBSERVE, (
            f"Zeroer reg_clk gated under test_en_i: edges={zreg_edges} window={IDLE_OBSERVE}"
        )
        dft_every = int(
            dma_edges == IDLE_OBSERVE
            and zaxi_edges == IDLE_OBSERVE
            and zreg_edges == IDLE_OBSERVE
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-FREE-RUN",
            "CHK-DFT-BYPASS-FREE-RUN: toggles_every_cycle="
            f"{dft_every} dma_edges={dma_edges} zeroer_axi_edges={zaxi_edges} "
            f"zeroer_reg_edges={zreg_edges} window={IDLE_OBSERVE} test_en_i=1 "
            "gating_enabled=1",
        )
        cg.mark_fence(self.fence, "dft-bypass-free-run-observed")

        # ---- S3: deassert test_en_i; assert rst_ni (reset held); gating still enabled ----
        cg.log_step(
            "S3",
            "deassert test_en_i; assert rst_ni (reset held); gating still enabled",
        )
        dut.tb_test_en_i.value = 0
        await self._reset_op(SmcResetOp.COLD_RST_LO)
        rst_asserted = await self._wait_reset_state(
            want_asserted=True,
            bound_smc=RESET_WAIT_BOUND_SMC,
            label="RESET_OVERRIDE_ASSERT",
        )
        assert rst_asserted.rst_primary_smc_clk_n == 0, rst_asserted

        # ---- S4: sample Zeroer axi/reg gated clocks with rst_ni asserted ----
        cg.log_step(
            "S4",
            "sample zeroer_axi_gated_clk / zeroer_reg_gated_clk for a fixed window with "
            "rst_ni asserted",
        )
        zaxi_rst_edges, zreg_rst_edges = await cg.count_enabled_pair_at_smc_rise(
            dut,
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        assert zaxi_rst_edges == IDLE_OBSERVE, (
            f"Zeroer axi_clk gated under rst_ni override: edges={zaxi_rst_edges} "
            f"window={IDLE_OBSERVE}"
        )
        assert zreg_rst_edges == IDLE_OBSERVE, (
            f"Zeroer reg_clk gated under rst_ni override: edges={zreg_rst_edges} "
            f"window={IDLE_OBSERVE}"
        )
        rst_every = int(
            zaxi_rst_edges == IDLE_OBSERVE and zreg_rst_edges == IDLE_OBSERVE
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-RESET-OVERRIDE-FREE-RUN",
            "CHK-RESET-OVERRIDE-FREE-RUN: toggles_every_cycle="
            f"{rst_every} zeroer_axi_edges={zaxi_rst_edges} "
            f"zeroer_reg_edges={zreg_rst_edges} window={IDLE_OBSERVE} rst_primary_smc_clk_n=0",
        )
        cg.mark_fence(self.fence, "reset-override-free-run-observed")

        # ---- Restore: release reset before ending the scenario ----
        await self._reset_op(SmcResetOp.COLD_RST_HI)
        await self._wait_reset_state(
            want_asserted=False,
            bound_smc=RESET_RECOVER_BOUND_SMC,
            label="RESET_OVERRIDE_RELEASE",
        )

        cg.assert_fence_order(
            self.fence,
            ["dft-bypass-free-run-observed", "reset-override-free-run-observed"],
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: dft-bypass-free-run-observed < reset-override-free-run-observed < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_cg_dft_reset_bringup_test_seq PASS")
