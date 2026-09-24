# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_003 ANCHOR: smc_cg_dft_reset_bringup_test

Two clock-gating bring-up properties on the DMA and Zeroer gaters:

* ``test_en_i`` bypass: with gating programmed on and both blocks idle the
  gaters take the clocks away; ``test_en_i`` = 1 gives them back every cycle;
  ``test_en_i`` = 0 with gating re-programmed takes them away again (A-B-A).
* Zeroer clocks under the primary reset: while ``rst_primary_smc_clk_n`` is
  asserted the Zeroer's gated clocks run every cycle. The cold reset also
  returns ``CLOCK_GATE_CONTROL`` to its generated reset, where the Zeroer
  enable is 0, and the leaf samples and records that enable inside the
  window. An enabled gate held in reset is therefore not reachable from the
  frontdoor on this bench, and the leaf does not claim that case: the claim
  is the free-running clock under reset with the enable at its reset value.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_reset_item import SmcResetItem, SmcResetOp

from . import smc_addr_map as _addr
from . import smc_cg_obs_utils as cg
from ._one_shot import _OneShot
from .smc_csr_seq_utils import SmcCsrSeq

# Every record this sequence emits goes through `cocotb.log`: a module-level
# `logging.getLogger(__name__)` is not captured by the cocotb/pyuvm runner, so
# the STEP/CHK/FENCE evidence written through one never reaches the kept log
# ([EVIDENCE-TOKEN-CONDITIONAL]).

HYST = 8
IDLE_OBSERVE = 16
# Reset-chain waits in time: the chain runs on the reference clock, whatever
# the sys-clock period; the polls below convert to clk_smc_i cycles.
RESET_WAIT_BOUND_NS = 2_000
RESET_RECOVER_BOUND_NS = 4_000
# Same bound the sibling smc_cg_test_mode_bypass_test_seq uses for its
# gated-off / re-enabled polls. Every wait using it raises on expiry.
GATE_OFF_TIMEOUT_SMC = 256

# Authoritative map (also re-exported via smc_cg_obs_utils for shared helpers).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK


class smc_cg_dft_reset_bringup_test_seq(SmcCsrSeq):
    """LIVE/CONNECTIVITY DFT test_en_i bypass (DMA+Zeroer) and Zeroer clocks free-running
    under the primary reset with the gating enable at its reset value (SMCCGP0_003)."""

    def __init__(self, name: str = "smc_cg_dft_reset_bringup_test_seq") -> None:
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
        # Read back: without this, a write that landed nowhere leaves the
        # gating enables at whatever they were, and every "clock still runs"
        # compare below then passes for the wrong reason.
        #
        # The scoreboard compares a whole 64-bit `expected=` word; the claim here
        # is only that the three fields this function programs took the write,
        # so the compare is masked to those fields below.
        back = await self.csr_read("CLOCK_GATE_CONTROL_VERIFY", CLOCK_GATE_CONTROL, length=8)
        programmed = DMA_CG_EN | ZEROER_CG_EN | CG_HYST_MASK
        assert (int(back) & programmed) == (nxt & programmed), (
            f"CLOCK_GATE_CONTROL readback 0x{int(back):016x} does not carry the "
            f"programmed gating enables/hysteresis from 0x{nxt:016x} "
            f"(compared under mask 0x{programmed:016x})"
        )

    async def _reset_op(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await _OneShot(item, f"reset_{op.value.lower()}_os").start(self.env.reset_agent.sequencer)
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

        # ---- S1: functional mode first, enable DMA+Zeroer gating, and OBSERVE
        # each of the three clocks actually gated off before claiming a bypass.
        #
        # This ordering is the whole point. Asserting test_en_i first and only
        # ever sampling "the clock still runs" passes identically on an inert
        # gater, on a CLOCK_GATE_CONTROL write that landed nowhere, and on a
        # real bypass -- nothing in the run distinguishes them
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]). smc_cg_test_mode_bypass_test_seq
        # takes the same three controls for the same reason.
        cg.log_step(
            "S1",
            "test_en_i=0; frontdoor CLOCK_GATE_CONTROL DMA_CG_EN=1 ZEROER_CG_EN=1 "
            "(readback verified); observe all three clocks gated off",
        )
        dut.tb_test_en_i.value = 0
        await self._program_cg(dma_en=True, zeroer_en=True)

        dma_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_dma_gated_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy", "tb_test_en_i"),
        )
        zaxi_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_axi_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_busy", "tb_test_en_i"),
        )
        zreg_off_at, _ = await cg.wait_gated_off(
            dut,
            "tb_zeroer_gated_reg_clk",
            hyst=HYST,
            idle_observe=4,
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_zeroer_cg_en", "tb_zeroer_busy", "tb_test_en_i"),
        )
        cg.mark_fence(self.fence, "all-gated-off-observed")

        # ---- S2: assert test_en_i and sample the same three gated clocks ----
        cg.log_step(
            "S2",
            "assert test_en_i; sample dma_gated_clk / zeroer_axi_gated_clk / "
            "zeroer_reg_gated_clk for a fixed window",
        )
        dut.tb_test_en_i.value = 1
        # Bounded poll for the first SMC rise that samples the DMA clock
        # enabled again, then count from there. A fixed ClockCycles settle
        # would absorb a bypass that never takes effect and pass on sim-timing
        # luck ([NO-BLIND-DELAY-SYNC]).
        bypass_seen_at = await cg.wait_enabled(
            dut,
            "tb_dma_gated_clk",
            timeout_smc=GATE_OFF_TIMEOUT_SMC,
            diag_names=("tb_dma_cg_en", "tb_dma_gater_busy", "tb_test_en_i"),
        )
        dma_edges, zaxi_edges, zreg_edges = await cg.count_enabled_triple_at_smc_rise(
            dut,
            "tb_dma_gated_clk",
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        # Each message names this run's gated-off observation of the same probe,
        # so a failure says which of the two states was not reached.
        assert dma_edges == IDLE_OBSERVE, (
            f"DMA clock gated under test_en_i: edges={dma_edges} "
            f"window={IDLE_OBSERVE} (this clock WAS observed gated off at smc "
            f"cycle {dma_off_at} with test_en_i=0, so the gater works and the "
            f"bypass does not)"
        )
        assert zaxi_edges == IDLE_OBSERVE, (
            f"Zeroer axi_clk gated under test_en_i: edges={zaxi_edges} "
            f"window={IDLE_OBSERVE} (observed gated off at smc cycle "
            f"{zaxi_off_at} with test_en_i=0)"
        )
        assert zreg_edges == IDLE_OBSERVE, (
            f"Zeroer reg_clk gated under test_en_i: edges={zreg_edges} "
            f"window={IDLE_OBSERVE} (observed gated off at smc cycle "
            f"{zreg_off_at} with test_en_i=0)"
        )
        dft_every = int(
            dma_edges == IDLE_OBSERVE and zaxi_edges == IDLE_OBSERVE and zreg_edges == IDLE_OBSERVE
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-DFT-BYPASS-FREE-RUN",
            "CHK-DFT-BYPASS-FREE-RUN: toggles_every_cycle="
            f"{dft_every} dma_edges={dma_edges} zeroer_axi_edges={zaxi_edges} "
            f"zeroer_reg_edges={zreg_edges} window={IDLE_OBSERVE} test_en_i=1 "
            f"gating_enabled=1; gated off first at smc cycles dma={dma_off_at} "
            f"zeroer_axi={zaxi_off_at} zeroer_reg={zreg_off_at} with "
            f"test_en_i=0, re-enabled {bypass_seen_at} smc cycle(s) after "
            f"test_en_i=1",
        )
        cg.mark_fence(self.fence, "dft-bypass-free-run-observed")

        # ---- S3: deassert test_en_i; assert the cold reset (reset held). The
        # reset returns CLOCK_GATE_CONTROL to its generated reset (enables 0),
        # so the window below observes a reset-cleared gate, and says so. ----
        cg.log_step(
            "S3",
            "deassert test_en_i; assert rst_ni (reset held); CLOCK_GATE_CONTROL returns to its "
            "reset, Zeroer gating enable 0",
        )
        dut.tb_test_en_i.value = 0
        await self._reset_op(SmcResetOp.COLD_RST_LO)
        rst_asserted = await self._wait_reset_state(
            want_asserted=True,
            bound_smc=int(RESET_WAIT_BOUND_NS / self.cfg.smc_clk_period_ns),
            label="RESET_OVERRIDE_ASSERT",
        )
        assert rst_asserted.rst_primary_smc_clk_n == 0, rst_asserted

        # ---- S4: sample Zeroer axi/reg gated clocks with rst_ni asserted ----
        cg.log_step(
            "S4",
            "sample zeroer_axi_gated_clk / zeroer_reg_gated_clk for a fixed window with "
            "rst_ni asserted",
        )
        cg_en_before = int(dut.tb_zeroer_cg_en.value)
        zaxi_rst_edges, zreg_rst_edges = await cg.count_enabled_pair_at_smc_rise(
            dut,
            "tb_zeroer_gated_axi_clk",
            "tb_zeroer_gated_reg_clk",
            IDLE_OBSERVE,
        )
        cg_en_after = int(dut.tb_zeroer_cg_en.value)
        assert zaxi_rst_edges == IDLE_OBSERVE, (
            f"Zeroer axi_clk gated under the primary reset: edges={zaxi_rst_edges} "
            f"window={IDLE_OBSERVE}"
        )
        assert zreg_rst_edges == IDLE_OBSERVE, (
            f"Zeroer reg_clk gated under the primary reset: edges={zreg_rst_edges} "
            f"window={IDLE_OBSERVE}"
        )
        # The register reset is what the token records: the enable is 0 across
        # the window, so this is a reset-cleared gate running free, not an
        # enabled gate being overridden.
        assert cg_en_before == 0 and cg_en_after == 0, (
            f"tb_zeroer_cg_en={cg_en_before}/{cg_en_after} across the reset window; the cold "
            f"reset was expected to return CLOCK_GATE_CONTROL to its reset (enable 0)"
        )
        rst_every = int(zaxi_rst_edges == IDLE_OBSERVE and zreg_rst_edges == IDLE_OBSERVE)
        cg.emit_chk(
            self.chk_seen,
            "CHK-RESET-OVERRIDE-FREE-RUN",
            "CHK-RESET-OVERRIDE-FREE-RUN: toggles_every_cycle="
            f"{rst_every} zeroer_axi_edges={zaxi_rst_edges} "
            f"zeroer_reg_edges={zreg_rst_edges} window={IDLE_OBSERVE} rst_primary_smc_clk_n=0 "
            f"zeroer_cg_en={cg_en_before}->{cg_en_after} (CLOCK_GATE_CONTROL at its reset: the "
            "clocks run free under reset with the gate disabled; an enabled gate held in reset is "
            "not reachable from the frontdoor and is not claimed)",
        )
        cg.mark_fence(self.fence, "reset-override-free-run-observed")

        # ---- Restore: release reset before ending the scenario ----
        await self._reset_op(SmcResetOp.COLD_RST_HI)
        await self._wait_reset_state(
            want_asserted=False,
            bound_smc=int(RESET_RECOVER_BOUND_NS / self.cfg.smc_clk_period_ns),
            label="RESET_OVERRIDE_RELEASE",
        )

        # ---- S5: A-B-A. Out of reset, in functional mode, gating programmed
        # again and both blocks idle -- the gaters must take the clocks back.
        # This is the one measurement in the testcase whose value no earlier
        # assert pins: a `test_en_i` input that latches high on first assertion,
        # a bypass term that never clears, or a reset override that never
        # releases all leave these three at IDLE_OBSERVE and fail here.
        cg.log_step(
            "S5",
            "reset released, test_en_i=0, gating re-programmed: the same three clocks must re-gate",
        )
        # The cold reset in S3 restored CLOCK_GATE_CONTROL to its generated
        # reset, where both enables are 0 (smc_base_config.h:
        # CLOCK_GATE_CONTROL__DMA_CG_EN_reset = 0x0). Re-program them before
        # observing the re-gate: without this the gaters are correctly disabled
        # and the bounded wait below expires against a DUT that is behaving.
        await self._program_cg(dma_en=True, zeroer_en=True)
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

        # Order PLUS strictly increasing simulation timestamps.
        # `assert_fence_order` alone is satisfied by construction in a
        # straight-line body and cannot fail on any RTL -- its own docstring
        # says so -- so a non-vacuity token resting on it certifies nothing.
        # `assert_fence_progress` adds the DUT-time claim and returns the
        # timestamps for the token.
        fence_times = cg.assert_fence_progress(
            self.fence,
            [
                "all-gated-off-observed",
                "dft-bypass-free-run-observed",
                "reset-override-free-run-observed",
                "bypass-released-regated-observed",
            ],
        )
        # Measured contrast: the same three probes, equal-length windows, both
        # polarities. The test_en_i=1 half was asserted at S2 and is carried
        # here as evidence only; the re-gate half is asserted for the first
        # time on this line.
        assert rel_dma == 0 and rel_zaxi == 0 and rel_zreg == 0, (
            f"clock gating never resumed after test_en_i=0 and reset release: "
            f"the same {IDLE_OBSERVE}-cycle window still samples "
            f"dma_enabled={rel_dma} zeroer_axi_enabled={rel_zaxi} "
            f"zeroer_reg_enabled={rel_zreg} (under test_en_i=1 the same probes "
            f"read {dma_edges}/{zaxi_edges}/{zreg_edges} of {IDLE_OBSERVE}); "
            f"with no return to the gated state the free-run evidence above "
            f"proves nothing"
        )
        cg.emit_chk(
            self.chk_seen,
            "CHK-NONVAC",
            "CHK-NONVAC: all-gated-off-observed@{}ns < "
            "dft-bypass-free-run-observed@{}ns < "
            "reset-override-free-run-observed@{}ns < "
            "bypass-released-regated-observed@{}ns; test_en_i=1 enabled "
            "dma={}/{} zeroer_axi={}/{} zeroer_reg={}/{}; test_en_i=0 re-gated "
            "at smc_cycle={} then enabled dma={}/{} zeroer_axi={}/{} "
            "zeroer_reg={}/{}".format(
                fence_times[0],
                fence_times[1],
                fence_times[2],
                fence_times[3],
                dma_edges,
                IDLE_OBSERVE,
                zaxi_edges,
                IDLE_OBSERVE,
                zreg_edges,
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
        cocotb.log.info("smc_cg_dft_reset_bringup_test_seq PASS")
