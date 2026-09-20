# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clear ESRC CTRL.MODULE_ENABLE while the boot phase is running, and drive the
alert-threshold exit out of BootPhaseDone.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `entropy_src_main_sm` holds 72 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`. 66 of them are the SHA-3 conditioner and
firmware-override states, which `hw/ip/entropy_source/rtl/entropy_source.sv:1026-1033`
ties off (`fw_ov_ent_insert_i`/`fw_ov_sha3_start_i` at 0, `bypass_mode_i` at 1)
and which a coverage waiver already carries. The remainder are inside states the
SM does reach and are driven from one software register:

* `vendor/lowRISC/opentitan/upstream/hw/ip/entropy_src/rtl/entropy_src_main_sm.sv:107`
  -- `BootPostHTChk` taking its `!enable_i` exit to `Idle`.
* :120 -- the same `!enable_i` exit from `BootPhaseDone`.
* :127 -- `BootPhaseDone -> AlertState` when a health-test window finishes and
  the accumulated failure count has reached ALERT_THRESHOLD.

`enable_i` is `CTRL.MODULE_ENABLE` (`entropy_source.sv:1025`) and
`alert_thresh_fail_i` is `any_fail_count >= ALERT_THRESHOLD` (:1031), so both
come from CSRs this test writes over the frontdoor. No suite leaf clears
MODULE_ENABLE after bring-up, which is why the arms are dark.

Stimulus, in three parts:

1. Bring the entropy source up the way the shared bring-up does -- generators
   off, configure, generators on, wait for the first seed -- which parks the SM
   in `BootPhaseDone`. Clear `CTRL.MODULE_ENABLE`, then set it again. That is
   the :120 exit.
2. Repeat the enable/disable pair with a seeded delay between the re-enable and
   the disable. `BootPostHTChk` is one cycle wide in this integration
   (`bypass_stage_rdy_i` is tied to 1 at `entropy_source.sv:1034`), so its
   `!enable_i` exit is only taken when the disable write lands in exactly that
   cycle. The sweep varies where the write lands; it is a probe, not a
   guarantee, and the leaf does not fail if the cycle is missed.
3. With the module disabled, program ALERT_THRESHOLD down to 1 and
   HEALTH_TEST_WINDOW_SIZE down to a short window, then re-enable. The SP 800-90B
   APT and Markov thresholds are sized for the full 2048-sample window, so a
   short window fails them by construction; the first failing window reaches the
   threshold of 1 and takes :127 into `AlertState`.

MAIN_SM_STATUS is read after each step and logged. Nothing read is compared
against an expectation: this leaf does not claim the SM landed in any particular
state, only that the writes were issued.

FIPS_LOCK is deliberately never written, so ALERT_THRESHOLD and
HEALTH_TEST_WINDOW_SIZE stay writable for part 3.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE, sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
)

ESRC_CTRL = sym("ENTROPY_SOURCE_CTRL_REG_ADDR")
ESRC_ALERT_THRESHOLD = sym("ENTROPY_SOURCE_ALERT_THRESHOLD_REG_ADDR")
ESRC_HEALTH_TEST_WINDOW_SIZE = sym("ENTROPY_SOURCE_HEALTH_TEST_WINDOW_SIZE_REG_ADDR")
ESRC_MAIN_SM_STATUS = sym("ENTROPY_SOURCE_MAIN_SM_STATUS_REG_ADDR")
ESRC_ALERT_SUMMARY_FAIL_COUNTS = sym("ENTROPY_SOURCE_ALERT_SUMMARY_FAIL_COUNTS_REG_ADDR")

# CTRL with the whitener on, built from the field metadata so MODULE_ENABLE --
# which resets to 1 -- keeps whatever this test asks for and every other field
# keeps its reset value.
CTRL_ENABLED = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1, SHA256_WHITENING_ENABLE=1)
CTRL_DISABLED = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0, SHA256_WHITENING_ENABLE=1)

# A window far below the 2048-sample reset. The APT and Markov thresholds are
# sized for the full window, so every short window fails them.
SHORT_WINDOW = 0x40

# Seeded delays, in core cycles, between a re-enable and the following disable.
# The spread straddles the few-cycle boot restart so at least one iteration has
# a chance of landing in the single-cycle BootPostHTChk.
DISABLE_SWEEP_ITERATIONS = 24
DISABLE_DELAY_MAX = 40

# Bound on the post-alert settle. One short health-test window is far quicker;
# the cap stops a window that never wraps from spending the run timeout here.
ALERT_SETTLE_CYCLES = 40_000


@pyuvm.test()
class sep_cov_esrc_disable_alert_walk_test(sep_base_test):
    """ESRC module-disable exits and the alert-threshold exit. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        try:
            self.stim = SepCovStim(self)
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")

            await self._disable_from_boot_phase_done()
            await self._disable_delay_sweep()
            await self._alert_threshold_exit()
        finally:
            noise.kill()

    async def _log_state(self, label: str) -> None:
        status = await self.stim._rd(ESRC_MAIN_SM_STATUS)
        self.logger.info(
            "cov stimulus: %s -- MAIN_SM_STATUS=0x%08x, logged not graded", label, status
        )

    async def _disable_from_boot_phase_done(self) -> None:
        """Part 1: the BootPhaseDone !enable_i exit."""
        await self._log_state("after first seed")
        await self.stim._wr(ESRC_CTRL, CTRL_DISABLED)
        await ClockCycles(cocotb.top.clk_i, 20)
        await self._log_state("MODULE_ENABLE cleared")
        await self.stim._wr(ESRC_CTRL, CTRL_ENABLED)
        await ClockCycles(cocotb.top.clk_i, 20)
        await self._log_state("MODULE_ENABLE set again")

    async def _disable_delay_sweep(self) -> None:
        """Part 2: probe the one-cycle BootPostHTChk !enable_i exit."""
        rng = SepSeededRng(self.random_seed())
        for i in range(DISABLE_SWEEP_ITERATIONS):
            delay = rng.getrandbits(16) % DISABLE_DELAY_MAX
            await self.stim._wr(ESRC_CTRL, CTRL_DISABLED)
            await ClockCycles(cocotb.top.clk_i, 8)
            await self.stim._wr(ESRC_CTRL, CTRL_ENABLED)
            if delay:
                await ClockCycles(cocotb.top.clk_i, delay)
            await self.stim._wr(ESRC_CTRL, CTRL_DISABLED)
            self.logger.info(
                "cov stimulus: disable sweep %d/%d, re-enable-to-disable delay %d cycles",
                i + 1,
                DISABLE_SWEEP_ITERATIONS,
                delay,
            )
        await self.stim._wr(ESRC_CTRL, CTRL_ENABLED)
        await self._log_state("after the disable sweep")

    async def _alert_threshold_exit(self) -> None:
        """Part 3: a short health-test window against a threshold of 1."""
        await self.stim._wr(ESRC_CTRL, CTRL_DISABLED)
        await self.stim._wr(
            ESRC_ALERT_THRESHOLD, ENTROPY_SOURCE.value("ALERT_THRESHOLD", THRESHOLD=1)
        )
        await self.stim._wr(
            ESRC_HEALTH_TEST_WINDOW_SIZE,
            ENTROPY_SOURCE.value("HEALTH_TEST_WINDOW_SIZE", SIZE=SHORT_WINDOW),
        )
        await self.stim._wr(ESRC_CTRL, CTRL_ENABLED)
        await ClockCycles(cocotb.top.clk_i, ALERT_SETTLE_CYCLES)
        await self._log_state("short window against ALERT_THRESHOLD=1")
        counts = await self.stim._rd(ESRC_ALERT_SUMMARY_FAIL_COUNTS)
        self.logger.info(
            "cov stimulus: ALERT_SUMMARY_FAIL_COUNTS=0x%08x, logged not graded", counts
        )
