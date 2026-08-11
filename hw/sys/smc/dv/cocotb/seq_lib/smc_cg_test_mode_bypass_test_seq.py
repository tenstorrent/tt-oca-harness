# SPDX-License-Identifier: Apache-2.0
"""
DV-CARD: SMC_CG_TEST_MODE_BYPASS_TEST ANCHOR: smc_cg_test_mode_bypass_test
DV-CARD-REVISION: 1 RECORD-SHA256: c4d8b90225e96f8c7796fabb3370409dc3db39898ca34e52d486363aef52ff49
DV-CARD-SOURCE: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_csr_seq_utils import SmcCsrSeq
from . import smc_cg_obs_utils as cg
from . import smc_addr_map as _addr

_LOG = cocotb.log

HYST = 8
IDLE_OBSERVE = 16
GATE_OFF_TIMEOUT_SMC = 256

# Authoritative map (also re-exported via smc_cg_obs_utils for shared helpers).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK


class smc_cg_test_mode_bypass_test_seq(SmcCsrSeq):
    """LIVE test_en_i DFT bypass of DMA + Zeroer clock gaters."""

    def __init__(self, name: str = "smc_cg_test_mode_bypass_test_seq") -> None:
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

    async def body(self) -> None:
        dut = self._dut()
        for port in (
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            "tb_test_en_i",
        ):
            assert hasattr(dut, port), f"missing TB port {port}"

        # Ensure functional mode first, configure otherwise-gating preconditions.
        dut.tb_test_en_i.value = 0
        cg.log_step(
            "S1",
            "DMA cg enabled + idle (would gate); assert test_en_i; DMA clock stays on",
        )
        await self._program_cg(dma_en=True, zeroer_en=True)
        await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy"),
        )
        # Positive control: was gated. Now assert DFT bypass.
        dut.tb_test_en_i.value = 1
        await ClockCycles(dut.clk_smc_i, 4)
        # Exact every-cycle via per-SMC-rise sample (avoids edge-counter ±1 races).
        edges = await cg.count_enabled_at_smc_rise(
            dut, "tb_dma_gated_clk", IDLE_OBSERVE
        )
        assert edges == IDLE_OBSERVE, (
            f"DMA clock gated under test_en_i: edges={edges} window={IDLE_OBSERVE}"
        )
        dma_every = int(edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-DMA",
            f"CHK-DFT-BYPASS-DMA: toggles_every_cycle={dma_every} edges={edges} "
            f"window={IDLE_OBSERVE} test_en_i=1",
        )
        cg.mark_fence(self.fence, "dma-bypass-observed")

        # ---- S2/S3: Zeroer axi + reg under otherwise-gating + test_en ----
        cg.log_step(
            "S2",
            "Zeroer axi path would gate; with test_en_i axi_clk stays enabled",
        )
        cg.log_step(
            "S3",
            "Zeroer reg path would gate; with test_en_i reg_clk stays enabled",
        )
        # test_en already 1; confirm both Zeroer clocks continuous while CG enabled
        # and idle (the otherwise-gating precondition proven in ZEROER_* tests).
        await ClockCycles(dut.clk_smc_i, HYST + 4)
        zaxi = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE
        )
        zreg = await cg.count_enabled_at_smc_rise(
            dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE
        )
        assert zaxi == IDLE_OBSERVE, (
            f"axi_clk gated under test_en_i: edges={zaxi} window={IDLE_OBSERVE}"
        )
        assert zreg == IDLE_OBSERVE, (
            f"reg_clk gated under test_en_i: edges={zreg} window={IDLE_OBSERVE}"
        )
        z_every = int(zaxi == IDLE_OBSERVE and zreg == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-ZEROER",
            "CHK-DFT-BYPASS-ZEROER: "
            f"axi_and_reg_toggles_every_cycle={z_every} "
            f"axi_edges={zaxi} reg_edges={zreg} window={IDLE_OBSERVE} test_en_i=1",
        )
        cg.mark_fence(self.fence, "zeroer-bypass-observed")

        # Restore functional mode.
        dut.tb_test_en_i.value = 0

        cg.assert_fence_order(
            self.fence, ["dma-bypass-observed", "zeroer-bypass-observed"]
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: dma-bypass-observed < zeroer-bypass-observed < PASS",
        )
        cg.mark_fence(self.fence, "PASS")
        _LOG.info("smc_cg_test_mode_bypass_test_seq PASS")
