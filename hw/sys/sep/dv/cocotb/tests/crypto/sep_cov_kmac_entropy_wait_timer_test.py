# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Request a KMAC entropy refresh from the ready state with the EDN wait timer
set short, so the entropy FSM re-enters StRandEdn and then expires out of it.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. ERR_CODE and STATUS are read and logged, never compared.

Target, `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/kmac_entropy.sv`:

* StRandReady -> StRandEdn (:593) needs `mode_q == EntropyModeEdn` together
  with `entropy_refresh_req_i` or `threshold_hit_q`. `kmac.sv:532` drives
  `entropy_refresh_req` from `CMD.entropy_req`, and `kmac.sv:537` drives the
  threshold from ENTROPY_REFRESH_THRESHOLD_SHADOWED. No leaf writes either, so
  the only StRandEdn entry the suite drives is the one out of StRandReset.
* StRandEdn -> StRandErrWaitExpired (:614) needs `timer_expired` with a
  non-zero limit. `kmac.sv:530-531` drives the prescaler and the limit from
  ENTROPY_PERIOD, whose reset value leaves the timer disabled.
* StRandErrWaitExpired -> StRandErr (:685) follows unconditionally, and
  StRandErr -> StRandReset (:712) needs `err_processed_i`.

Stimulus, in order: bring the entropy complex up so the first EDN reseed
completes and the FSM parks in StRandReady; program ENTROPY_PERIOD with the
shortest non-zero wait timer and no prescaler; write CMD.entropy_req, which
sends the FSM back to StRandEdn where the short timer expires before EDN can
answer; read ERR_CODE; write CMD.err_processed to return to StRandReset. The
run then restores the reset ENTROPY_PERIOD so the timer is disabled again for
whatever shares the build.

A short wait timer is a legal configuration: the register exists so software
can bound an EDN stall, and the FSM reports the expiry in ERR_CODE rather than
as a bus error, so no access here is marked `allow_error`.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)
from seq_lib.sep_kmac_seq import (
    KMAC_CFG_SHADOWED,
    KMAC_CMD,
    KMAC_ERR_CODE,
    KMAC_MODE,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

KMAC_ENTROPY_PERIOD = KMAC.addr("ENTROPY_PERIOD")

CMD_ENTROPY_REQ = KMAC.field_mask("CMD", "entropy_req")
CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")

# The shortest non-zero limit, with the prescaler left at zero, so the timer
# expires in the fewest cycles the register can express.
WAIT_TIMER_LIMIT = 1
WAIT_TIMER_PRESCALER = 0

REFRESH_REQUESTS = 2
SETTLE_CYCLES = 400
STATUS_POLLS = 400
POLL_GAP_CYCLES = 20


@pyuvm.test()
class sep_cov_kmac_entropy_wait_timer_test(sep_base_test):
    """KMAC EDN refresh request and wait-timer expiry. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        try:
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

            self.kmac = SepKmac(self)
            await self._seed_and_park()
            await self._short_timer_refreshes()
        finally:
            await self.kmac._wr(KMAC_ENTROPY_PERIOD, 0)
            noise.kill()

    async def _poll_idle(self, label: str) -> None:
        for _ in range(STATUS_POLLS):
            status = await self.kmac._rd(KMAC_STATUS)
            if status & KMAC_STATUS_IDLE:
                return
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: KMAC STATUS.idle not seen at %s, continuing", label)

    async def _seed_and_park(self) -> None:
        """First EDN reseed, so the FSM leaves StRandReset and parks in ready."""
        cfg = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )
        # CFG_SHADOWED is shadowed: the value must be written twice.
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self._poll_idle("initial EDN reseed")
        self.logger.info("cov stimulus: KMAC seeded from EDN, entropy FSM in its ready state")

    async def _short_timer_refreshes(self) -> None:
        period = (
            WAIT_TIMER_LIMIT << KMAC.field_lsb("ENTROPY_PERIOD", "wait_timer")
        ) | (WAIT_TIMER_PRESCALER << KMAC.field_lsb("ENTROPY_PERIOD", "prescaler"))
        await self.kmac._wr(KMAC_ENTROPY_PERIOD, period)
        self.logger.info(
            "cov stimulus: ENTROPY_PERIOD=0x%08x (wait_timer=%d, prescaler=%d)",
            period,
            WAIT_TIMER_LIMIT,
            WAIT_TIMER_PRESCALER,
        )

        for req in range(REFRESH_REQUESTS):
            await self.kmac._wr(KMAC_CMD, CMD_ENTROPY_REQ)
            await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
            err = await self.kmac._rd(KMAC_ERR_CODE)
            self.logger.info(
                "cov stimulus: refresh %d -- CMD.entropy_req with a %d-tick wait timer, "
                "ERR_CODE=0x%08x, logged not graded",
                req,
                WAIT_TIMER_LIMIT,
                err,
            )
            await self.kmac._wr(KMAC_CMD, CMD_ERR_PROCESSED)
            await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
            self.logger.info(
                "cov stimulus: refresh %d -- CMD.err_processed written, entropy FSM released", req
            )
