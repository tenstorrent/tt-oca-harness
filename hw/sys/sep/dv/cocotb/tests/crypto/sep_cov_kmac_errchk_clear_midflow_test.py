# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raise a KMAC command-sequence error in each mid-operation stage and clear it
there, so kmac_errchk returns to idle from feed, processing and squeezing.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. ERR_CODE and STATUS are read and logged, never compared.

Target, `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/kmac_errchk.sv:463`:

    if (st_d != StTerminalError &&
        mubi4_test_true_strict(clear_after_error_i)) st_d = StIdle;

`clear_after_error_i` comes from CMD.err_processed (`kmac.sv:1123`). The case
bodies themselves give StMsgFeed, StProcessing and StSqueezing exactly one
forward exit each (:417, :423, :435), so this line is the only source of the
three StMsgFeed / StProcessing / StSqueezing -> StIdle arcs.

`sep_cov_kmac_err_squeeze_walk_test` already drives every software error check,
but it finishes each stage with CMD.done before it writes CMD.err_processed, so
the FSM is already in StIdle when the clear lands and these three arcs stay
dark. The difference here is only the order: the clear is written while the
stage is still live.

Stimulus, three walks. In each, a valid SHAKE-256 run is taken to the target
stage, a command the stage refuses is issued so `err_swsequence` (:215) latches,
and CMD.err_processed is written immediately, without a CMD.done first:

* StMsgFeed: START, one message word, a second START, then err_processed.
* StProcessing: START, message, PROCESS, a second START, then err_processed.
* StSqueezing: absorb to the squeeze stage, MANUAL_RUN, a PROCESS the stage
  refuses, then err_processed.

`block_swcmd` (:237) is combinational on the refused command, so it releases as
soon as that command retires and the err_processed write reaches the FSM on the
following access.

Every access is a legal register access answered with OKAY -- KMAC reports a
refused command in ERR_CODE, not as a bus error -- so no access here is marked
`allow_error`.

RANDCFG: the message words come from the run seed through `SepSeededRng`. They
are not a key, nonce or token, and nothing leaves the simulation.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
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
    KMAC_CMD_DONE,
    KMAC_CMD_PROCESS,
    KMAC_CMD_START,
    KMAC_ERR_CODE,
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STATUS_SQUEEZE,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

# kmac_pkg.sv command encodings not exported by the sequence library.
KMAC_CMD_MANUAL_RUN = 0x31
KMAC_CMD_NONE = 0x00

CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")

MSG_WORDS = 8
STATUS_POLLS = 400
POLL_GAP_CYCLES = 20
SETTLE_CYCLES = 40


@pyuvm.test()
class sep_cov_kmac_errchk_clear_midflow_test(sep_base_test):
    """err_processed written while the stage is still live. Stimulus only."""

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
            rng = SepSeededRng(self.random_seed())
            await self._clear_in_msgfeed(rng)
            await self._clear_in_processing(rng)
            await self._clear_in_squeezing(rng)
        finally:
            noise.kill()

    # --- helpers -------------------------------------------------------------

    async def _poll(self, mask: int, label: str) -> int:
        status = 0
        for _ in range(STATUS_POLLS):
            status = await self.kmac._rd(KMAC_STATUS)
            if status & mask:
                return status
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: KMAC STATUS bit not seen at %s, continuing", label)
        return status

    async def _configure(self) -> None:
        cfg = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )
        # CFG_SHADOWED is shadowed: the value must be written twice.
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self._poll(KMAC_STATUS_IDLE, "pre-start")

    async def _feed(self, rng: SepSeededRng, words: int = MSG_WORDS) -> None:
        for _ in range(words):
            await self.kmac._wr(KMAC_MSG_FIFO, rng.getrandbits(32))

    async def _clear_now(self, stage: str) -> None:
        """Write CMD.err_processed with the stage still live, then let go."""
        err = await self.kmac._rd(KMAC_ERR_CODE)
        self.logger.info(
            "cov stimulus: refused command in %s -- ERR_CODE=0x%08x, logged not graded", stage, err
        )
        await self.kmac._wr(KMAC_CMD, CMD_ERR_PROCESSED)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_NONE)
        await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
        await self._poll(KMAC_STATUS_IDLE, f"{stage} cleared")
        self.logger.info("cov stimulus: %s cleared without an intervening CMD.done", stage)

    async def _recover(self) -> None:
        """Retire the aborted operation so the next walk starts from FlushIdle.

        `err_processed` clears kmac_errchk but does not finish the msgfifo flush
        that PROCESS started. kmac_msgfifo.sv:332 assumes `fifo_valid_i |->
        flush_st == FlushIdle` -- "No messages in between process_i and
        clear_i" -- so feeding the next walk while that flush is outstanding
        drives an input the IP declares illegal. CMD.done here is recovery
        AFTER the cleared-without-done behaviour has already been driven, so it
        does not weaken what this leaf exercises.
        """
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_NONE)
        await self._poll(KMAC_STATUS_IDLE, "recovered")

    # --- the three walks -----------------------------------------------------

    async def _clear_in_msgfeed(self, rng: SepSeededRng) -> None:
        await self._configure()
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._feed(rng)
        # A second START is not a command the feed stage accepts.
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._clear_now("message feed")
        await self._recover()

    async def _clear_in_processing(self, rng: SepSeededRng) -> None:
        await self._configure()
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._feed(rng)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        # A START while the absorb is running is not a command that stage accepts.
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._clear_now("processing")
        await self._recover()

    async def _clear_in_squeezing(self, rng: SepSeededRng) -> None:
        await self._configure()
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._feed(rng)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._poll(KMAC_STATUS_SQUEEZE, "absorbed")
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_MANUAL_RUN)
        # A PROCESS while the manual run is squeezing is not a command that
        # stage accepts.
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._clear_now("squeezing")
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._poll(KMAC_STATUS_IDLE, "post-done")
