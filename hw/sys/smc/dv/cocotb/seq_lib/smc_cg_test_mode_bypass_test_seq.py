# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_CG_TEST_MODE_BYPASS_TEST ANCHOR: smc_cg_test_mode_bypass_test
"""

from __future__ import annotations

import cocotb

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from .smc_csr_seq_utils import SmcCsrSeq

# Every record this sequence emits goes through `cocotb.log`: a module-level
# `logging.getLogger(__name__)` is not captured by the cocotb/pyuvm runner, so
# the STEP/CHK/FENCE evidence written through one never reaches the kept log
# ([EVIDENCE-TOKEN-CONDITIONAL]).

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

    async def _program_cg(self, *, dma_en: bool, zeroer_en: bool, hyst: int = HYST) -> None:
        cur = await self.csr_read("CLOCK_GATE_CONTROL_RD", CLOCK_GATE_CONTROL, length=8)
        nxt = (cur & ~DMA_CG_EN & ~ZEROER_CG_EN & ~CG_HYST_MASK) | (
            (hyst << CG_HYST_SHIFT) & CG_HYST_MASK
        )
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

        dut.tb_test_en_i.value = 0
        cg.log_step(
            "S1",
            "DMA cg enabled + idle (would gate); assert test_en_i; DMA clock stays on",
        )
        await self._program_cg(dma_en=True, zeroer_en=True)

        # ---- Positive controls, ALL taken with test_en_i still 0 ----
        # Each of the three clocks this testcase later claims is "bypassed" must
        # first be observed actually gated off by the same gater in the same
        # run; otherwise a gater that never gates passes the bypass compare
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). Every wait is bounded and raises
        # on expiry, so none of them is a blind delay.
        dma_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy"),
        )
        zaxi_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_busy"),
        )
        zreg_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_busy"),
        )
        cg.mark_fence(self.fence, "all-gated-off-observed")

        dut.tb_test_en_i.value = 1
        # Bounded settle, not a magic delay: poll for the first SMC rise that
        # samples the DMA gated clock enabled, then start the counted window
        # from there. The bound is the same GATE_OFF_TIMEOUT_SMC the gated-off
        # waits use, and expiry RAISES with the last observed state, so a bypass
        # that never takes effect fails here rather than being absorbed by a
        # longer wait ([NO-BLIND-DELAY-SYNC]).
        bypass_seen_at = await cg.wait_enabled(
            dut,
            "tb_dma_gated_clk",
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy", "tb_test_en_i"),
        )
        # Exact every-cycle via per-SMC-rise sample (avoids edge-counter ±1 races).
        edges = await cg.count_enabled_at_smc_rise(dut, "tb_dma_gated_clk", IDLE_OBSERVE)
        assert edges == IDLE_OBSERVE, (
            f"DMA clock gated under test_en_i: edges={edges} window={IDLE_OBSERVE}"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-DMA",
            f"CHK-DFT-BYPASS-DMA: gated_off_at_smc_cycle={dma_off_at} with "
            f"test_en_i=0, then enabled again {bypass_seen_at} smc cycle(s) "
            f"after test_en_i=1 and edges={edges} of window={IDLE_OBSERVE}",
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
        # test_en already 1; confirm both Zeroer clocks continuous while CG
        # enabled and idle. `zaxi_off_at` / `zreg_off_at` above are this run's
        # bounded observation of these same two clocks gated off by the same
        # gater with test_en_i=0, so a gater that never gates fails there
        # instead of passing here. The DMA window above already ran
        # IDLE_OBSERVE cycles under test_en_i=1, which is the settle these two
        # samples need.
        zaxi = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_axi_clk", IDLE_OBSERVE)
        zreg = await cg.count_enabled_at_smc_rise(dut, "tb_zeroer_gated_reg_clk", IDLE_OBSERVE)
        assert zaxi == IDLE_OBSERVE, (
            f"axi_clk gated under test_en_i: edges={zaxi} window={IDLE_OBSERVE} "
            f"(this clock WAS observed gated off at smc cycle {zaxi_off_at} "
            f"with test_en_i=0, so the gater works and the bypass does not)"
        )
        assert zreg == IDLE_OBSERVE, (
            f"reg_clk gated under test_en_i: edges={zreg} window={IDLE_OBSERVE} "
            f"(this clock WAS observed gated off at smc cycle {zreg_off_at} "
            f"with test_en_i=0, so the gater works and the bypass does not)"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-ZEROER",
            "CHK-DFT-BYPASS-ZEROER: "
            f"axi gated_off_at_smc_cycle={zaxi_off_at} reg "
            f"gated_off_at_smc_cycle={zreg_off_at} with test_en_i=0, then "
            f"axi_edges={zaxi} reg_edges={zreg} window={IDLE_OBSERVE} test_en_i=1",
        )
        cg.mark_fence(self.fence, "zeroer-bypass-observed")

        # ---- Release: functional mode restored, the gaters take the clocks
        # back (A-B-A). Everything above is sampled with test_en_i asserted; a
        # `test_en_i` input that latches high on first assertion, or a bypass
        # term that never clears once set, produces a byte-identical log. This
        # window is the one measurement in this testcase whose value NO earlier
        # assert pins: the same three probes, the same window length, sampled
        # after the bypass is released with both blocks still idle and both CG
        # enables still programmed. The wait is bounded and raises on expiry.
        dut.tb_test_en_i.value = 0
        dma_regate_at, _ = await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy", "tb_test_en_i"),
        )
        rel_dma, rel_zaxi, rel_zreg = await cg.count_enabled_triple_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        cg.mark_fence(self.fence, "bypass-released-regated-observed")

        # Fence order plus strictly increasing simulation timestamps;
        # `assert_fence_progress` returns the timestamps carried in the token
        # below.
        fence_times = cg.assert_fence_progress(
            self.fence,
            [
                "all-gated-off-observed",
                "dma-bypass-observed",
                "zeroer-bypass-observed",
                "bypass-released-regated-observed",
            ],
        )
        # Measured contrast, both halves on the same three probes over
        # equal-length windows. The test_en_i=1 half (`edges`/`zaxi`/`zreg`)
        # was already asserted at S1..S3 above and is carried here as evidence
        # only -- it is NOT this checker's fail path. The test_en_i=0 release
        # half is asserted for the first time here: a latched or never-clearing
        # bypass leaves these three at IDLE_OBSERVE and fails at this line.
        assert rel_dma == 0 and rel_zaxi == 0 and rel_zreg == 0, (
            f"DFT bypass release not observed on any probe: after test_en_i=0 "
            f"the same {IDLE_OBSERVE}-cycle window still samples "
            f"dma_enabled={rel_dma} zeroer_axi_enabled={rel_zaxi} "
            f"zeroer_reg_enabled={rel_zreg} (with test_en_i=1 the same probes "
            f"read {edges}/{zaxi}/{zreg} of {IDLE_OBSERVE}); the bypass never "
            f"released, so the test_en_i=1 evidence above proves nothing"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: all-gated-off-observed@{}ns < dma-bypass-observed@{}ns "
            "< zeroer-bypass-observed@{}ns < "
            "bypass-released-regated-observed@{}ns "
            "test_en_i=1 enabled dma={}/{} zeroer_axi={}/{} zeroer_reg={}/{}; "
            "test_en_i=0 re-gated at smc_cycle={} then enabled dma={}/{} "
            "zeroer_axi={}/{} zeroer_reg={}/{}".format(
                fence_times[0],
                fence_times[1],
                fence_times[2],
                fence_times[3],
                edges,
                IDLE_OBSERVE,
                zaxi,
                IDLE_OBSERVE,
                zreg,
                IDLE_OBSERVE,
                dma_regate_at,
                rel_dma,
                IDLE_OBSERVE,
                rel_zaxi,
                IDLE_OBSERVE,
                rel_zreg,
                IDLE_OBSERVE,
            ),
        )
        cg.mark_fence(self.fence, "PASS")
        cocotb.log.info("smc_cg_test_mode_bypass_test_seq PASS")
