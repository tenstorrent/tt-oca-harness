# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Declare KMAC ready with no entropy mode selected, then clear the error, so
the entropy FSM walks its incorrect-mode error branch and recovers.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. ERR_CODE is read and logged, never compared.

Target, `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/kmac_entropy.sv`.
The StRandReset case at :528 latches `mode_i` on `entropy_ready_i` and takes a
third leg:

* `EntropyModeSw` -> StSwSeedWait (:540)
* `EntropyModeEdn` -> StRandEdn (:546)
* anything else, which is `EntropyModeNone` -> StRandErrIncorrectMode (:555)

`seq_lib/sep_kmac_seq.build_kmac_cfg` always programs entropy_mode = EDN
together with entropy_ready, so the third leg, the StRandErrIncorrectMode and
StRandErr states, and the `err_processed` return StRandErr -> StRandReset
(:712) are all dark.

Stimulus: CFG_SHADOWED is written with entropy_ready set and entropy_mode left
at its reset value, which drives StRandReset -> StRandErrIncorrectMode ->
StRandErr. StRandErr holds until `err_processed_i`, so CMD.err_processed is
written next, which returns the FSM to StRandReset. The walk is repeated so
the recovered FSM is re-entered from a known state, and it finishes by
programming a valid EDN mode so whatever shares the build finds KMAC seeded.

The ESRC/DRBG/CSRNG/EDN stack is brought up first: the final valid-mode
configuration reseeds from EDN and would otherwise stall.

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

CFG_ENTROPY_READY = KMAC.field_mask("CFG_SHADOWED", "entropy_ready")
CFG_ENTROPY_MODE_MASK = KMAC.field_mask("CFG_SHADOWED", "entropy_mode")
CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")

# kmac_pkg.sv entropy-mode encodings: 0 is EntropyModeNone, which is the value
# the default leg of the StRandReset case rejects.
ENTROPY_MODE_NONE = 0

WALKS = 2
SETTLE_CYCLES = 200
STATUS_POLLS = 400
POLL_GAP_CYCLES = 20


@pyuvm.test()
class sep_cov_kmac_entropy_mode_error_test(sep_base_test):
    """KMAC entropy incorrect-mode error and its err_processed recovery.
    Stimulus only."""

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
            for walk in range(WALKS):
                await self._incorrect_mode_walk(walk)
            await self._restore_valid_mode()
        finally:
            noise.kill()

    async def _write_cfg(self, cfg: int) -> None:
        """CFG_SHADOWED is shadowed: the value must be written twice."""
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)

    async def _incorrect_mode_walk(self, walk: int) -> None:
        base = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )
        # build_kmac_cfg always programs EDN; clear the mode field so the
        # latched mode is EntropyModeNone while entropy_ready is still set.
        no_mode = (base & ~CFG_ENTROPY_MODE_MASK) | CFG_ENTROPY_READY
        no_mode |= ENTROPY_MODE_NONE << KMAC.field_lsb("CFG_SHADOWED", "entropy_mode")
        assert not no_mode & CFG_ENTROPY_MODE_MASK, (
            "stimulus precondition: entropy_mode must read back as EntropyModeNone"
        )

        await self._write_cfg(no_mode)
        await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
        err = await self.kmac._rd(KMAC_ERR_CODE)
        self.logger.info(
            "cov stimulus: walk %d -- entropy_ready with entropy_mode=None, "
            "ERR_CODE=0x%08x, logged not graded",
            walk,
            err,
        )

        await self.kmac._wr(KMAC_CMD, CMD_ERR_PROCESSED)
        await ClockCycles(cocotb.top.clk_i, SETTLE_CYCLES)
        self.logger.info(
            "cov stimulus: walk %d -- CMD.err_processed written, entropy FSM released", walk
        )

    async def _restore_valid_mode(self) -> None:
        valid = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )
        await self._write_cfg(valid)
        for _ in range(STATUS_POLLS):
            status = await self.kmac._rd(KMAC_STATUS)
            if status & KMAC_STATUS_IDLE:
                break
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: KMAC returned to a valid EDN entropy mode")
