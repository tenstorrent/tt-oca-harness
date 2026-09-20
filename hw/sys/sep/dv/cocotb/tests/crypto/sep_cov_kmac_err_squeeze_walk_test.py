# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive each KMAC software error check, and squeeze a SHAKE output past one
Keccak rate with the manual-run command.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `kmac` holds 269 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`. 157 of them are in `kmac_app`, which a
coverage waiver already carries (`hw/sys/sep/rtl/kmac_wrapper.sv:186` ties
`.app_i('0)`). Of the rest, `kmac_errchk` holds 19 and `kmac` 12, and they are
the checks and the squeeze command that no leaf issues:

* `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/kmac_errchk.sv:215`, :220-221
  -- `err_swsequence`, raised by a command the current stage does not accept.
* :259 -- `err_modestrength`, the mode / strength pairs the check at :254-258
  rejects: SHA-3 outside L224..L512, or SHAKE / cSHAKE outside L128 and L256.
* :271 -- `err_prefix`, raised when `kmac_en` is set and PREFIX's first six
  bytes are not `encode_string("KMAC")` (:266-272).
* :291 -- `err_entropy_ready`, raised when `kmac_en` is set and CFG's
  `entropy_ready` was never pulsed while idle (:286-293).
* :321, :434, :441-442 -- `StSqueezing`, the state the manual-run command
  enters, and the return to `StAbsorbed`; with
  `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/kmac.sv:445` (`sha3_run`),
  the signal that command drives.
* `kmac.sv:696-712` -- the ERR_CODE mux arms for an application, entropy or
  message-FIFO error source.

`seq_lib/sep_kmac_seq.py` programs a valid prefix, a supported mode / strength
pair and `entropy_ready` on every run, and it never issues a command out of
sequence or a manual run, which is why all of these are dark.

Stimulus, in two parts:

1. Five refused command sequences, each followed by a read of ERR_CODE and a
   `CMD.err_processed` write to clear it: a process command while idle; a second
   start command while a message is being fed; a SHA-3 start at strength L128
   with `en_unsupported_modestrength` clear; a keyed start with a PREFIX that is
   not `encode_string("KMAC")`; and a keyed start with `entropy_ready` clear.
2. A SHAKE-256 absorb followed by two manual-run commands, with the STATE
   window read after each. SHAKE-256's rate is 1088 bits, so reading past it
   needs the squeeze the manual-run command performs.

ERR_CODE, STATUS and the STATE words are read and logged. Nothing read is
compared against an expectation: this leaf does not claim the squeezed output is
the SHAKE stream, only that the squeeze ran. Every access is a legal register
access answered with OKAY -- KMAC reports its refusals in ERR_CODE, not as a bus
error -- so no access here is marked `allow_error`.

KMAC masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first.

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
    KMAC_KEY_LEN,
    KMAC_KEY_LEN_256,
    KMAC_KEY_SHARE0_0,
    KMAC_KEY_SHARE1_0,
    KMAC_KEY_WORDS,
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_NUM_PREFIX,
    KMAC_PREFIX_0,
    KMAC_PREFIX_WORD0,
    KMAC_PREFIX_WORD1,
    KMAC_STATE_S0,
    KMAC_STATE_S1,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STATUS_SQUEEZE,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

# kmac_pkg.sv:100-104 command encodings. START and PROCESS come from the
# sequence library; the manual run and the none-command do not.
KMAC_CMD_MANUAL_RUN = 0x31
KMAC_CMD_NONE = 0x00

CMD_ERR_PROCESSED = KMAC.field_mask("CMD", "err_processed")

CFG_ENTROPY_READY = KMAC.field_mask("CFG_SHADOWED", "entropy_ready")
CFG_EN_UNSUPPORTED = KMAC.field_mask("CFG_SHADOWED", "en_unsupported_modestrength")

# SHAKE-256's rate is 1088 bits = 34 words. Reading 48 words walks past one
# rate, which is what the manual-run squeeze supplies.
SHAKE256_RATE_WORDS = 34
SQUEEZE_READ_WORDS = 48
MANUAL_RUNS = 2

MSG_WORDS = 16

# Bounds on the STATUS polls. A KMAC absorb of this size settles in far fewer
# reads; the caps keep a stage that never settles from spending the run timeout
# in one loop.
STATUS_POLLS = 400
POLL_GAP_CYCLES = 20


@pyuvm.test()
class sep_cov_kmac_err_squeeze_walk_test(sep_base_test):
    """KMAC software error checks and the manual-run squeeze. Stimulus only."""

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
            await self._error_walk(rng)
            await self._squeeze_walk(rng)
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

    async def _write_cfg(self, cfg: int) -> None:
        """CFG_SHADOWED is shadowed: the value must be written twice."""
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)

    async def _write_prefix_words(self, word0: int, word1: int) -> None:
        await self.kmac._wr(KMAC_PREFIX_0, word0)
        await self.kmac._wr(KMAC_PREFIX_0 + 4, word1)
        for i in range(2, KMAC_NUM_PREFIX):
            await self.kmac._wr(KMAC_PREFIX_0 + i * 4, 0)

    async def _write_sw_key(self, rng: SepSeededRng) -> None:
        for i in range(KMAC_KEY_WORDS):
            await self.kmac._wr(KMAC_KEY_SHARE0_0 + i * 4, rng.getrandbits(32))
            await self.kmac._wr(KMAC_KEY_SHARE1_0 + i * 4, 0)

    async def _clear_error(self, label: str) -> None:
        err = await self.kmac._rd(KMAC_ERR_CODE)
        self.logger.info("cov stimulus: %s -- ERR_CODE=0x%08x, logged not graded", label, err)
        await self.kmac._wr(KMAC_CMD, CMD_ERR_PROCESSED)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_NONE)
        await self._poll(KMAC_STATUS_IDLE, f"{label} recovery")

    # --- part 1: the software error checks -----------------------------------

    async def _error_walk(self, rng: SepSeededRng) -> None:
        shake256 = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False
        )

        # A process command while the engine is idle.
        await self._write_cfg(shake256)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._clear_error("process command while idle")

        # A second start command while a message is being fed.
        await self._write_cfg(shake256)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self.kmac._wr(KMAC_MSG_FIFO, rng.getrandbits(32))
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        err = await self.kmac._rd(KMAC_ERR_CODE)
        self.logger.info(
            "cov stimulus: second start while feeding -- ERR_CODE=0x%08x, logged not graded", err
        )
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._poll(KMAC_STATUS_SQUEEZE, "recovery absorb")
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._clear_error("second start while feeding, cleared")

        # SHA-3 at strength L128, which the mode/strength check rejects, with
        # en_unsupported_modestrength left clear so the check blocks the command.
        unsupported = build_kmac_cfg(
            mode=KMAC_MODE["sha3"], kstrength=KMAC_STRENGTH[128], kmac_en=False
        )
        assert not unsupported & CFG_EN_UNSUPPORTED, (
            "stimulus precondition: en_unsupported_modestrength must stay clear"
        )
        await self._write_cfg(unsupported)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._clear_error("SHA-3 at strength L128")

        # A keyed start whose prefix is not encode_string("KMAC").
        await self.kmac._wr(KMAC_KEY_LEN, KMAC_KEY_LEN_256)
        await self._write_sw_key(rng)
        await self._write_prefix_words(KMAC_PREFIX_WORD0 ^ 0xFF, KMAC_PREFIX_WORD1)
        keyed = build_kmac_cfg(mode=KMAC_MODE["cshake"], kstrength=KMAC_STRENGTH[256], kmac_en=True)
        await self._write_cfg(keyed)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._clear_error("keyed start with a wrong PREFIX")

        # A keyed start with entropy_ready clear. build_kmac_cfg always sets it,
        # so it is masked out here.
        await self._write_prefix_words(KMAC_PREFIX_WORD0, KMAC_PREFIX_WORD1)
        await self._write_cfg(keyed & ~CFG_ENTROPY_READY)
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        await self._clear_error("keyed start with entropy_ready clear")

    # --- part 2: the manual-run squeeze --------------------------------------

    async def _read_state(self, words: int, label: str) -> None:
        first = None
        for i in range(words):
            s0 = await self.kmac._rd(KMAC_STATE_S0 + i * 4)
            s1 = await self.kmac._rd(KMAC_STATE_S1 + i * 4)
            if first is None:
                first = (s0 ^ s1) & 0xFFFF_FFFF
        self.logger.info(
            "cov stimulus: %s -- read %d STATE words, first 0x%08x, logged not graded",
            label,
            words,
            first or 0,
        )

    async def _squeeze_walk(self, rng: SepSeededRng) -> None:
        cfg = build_kmac_cfg(mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[256], kmac_en=False)
        await self._write_cfg(cfg)
        await self._poll(KMAC_STATUS_IDLE, "pre-start")
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        for _ in range(MSG_WORDS):
            await self.kmac._wr(KMAC_MSG_FIFO, rng.getrandbits(32))
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._poll(KMAC_STATUS_SQUEEZE, "first squeeze")
        await self._read_state(SHAKE256_RATE_WORDS, "first rate")

        for run in range(MANUAL_RUNS):
            await self.kmac._wr(KMAC_CMD, KMAC_CMD_MANUAL_RUN)
            await self._poll(KMAC_STATUS_SQUEEZE, f"manual run {run + 1}")
            await self._read_state(SQUEEZE_READ_WORDS, f"after manual run {run + 1}")

        await self.kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._poll(KMAC_STATUS_IDLE, "post-done")
