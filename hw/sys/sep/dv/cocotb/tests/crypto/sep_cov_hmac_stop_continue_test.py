# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Save and restore an HMAC context with the stop/continue commands, wipe the
secret, and drive each of the four software error codes.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `hmac` holds 29 uncovered lines, `hmac_core` 12, `prim_sha2` 11,
`prim_sha2_pad` 15 and `prim_sha2_32` 13 in the merged VCS run
`build/runs/20260919_225443__vcs__all`. The suite only ever runs a hash straight
through -- start, push, process -- so three groups of arms stay dark, and all
three are reached from the CMD, CFG, KEY and MSG_LENGTH registers:

* The stop/continue context save and restore.
  `vendor/lowRISC/opentitan/upstream/hw/ip/hmac/rtl/hmac.sv:170` and :182-192
  are `DoneAwaitMessageComplete` and `DoneAwaitHashComplete`, the done states a
  stop enters; :647-650 restores `message_length` from MSG_LENGTH_LOWER and
  MSG_LENGTH_UPPER on a continue.
  `vendor/lowRISC/opentitan/upstream/hw/ip/hmac/rtl/hmac_core.sv:343-346` is the
  `StIdle -> StMsg` continue arm, :381-383 the stop exit from `StMsg` and :398
  the inner-round `StDone`. `prim_sha2_pad.sv:353` reloads `tx_count` from the
  restored message length, and `prim_sha2.sv:353-354` and :384-385 are the FIFO
  idle arms the stop takes.
* `WIPE_SECRET`. `hmac.sv:215` (`secret_key_d = {32{wipe_v}}`) and the
  `wipe_v_i` arms in `prim_sha2.sv:94`, :125, :148, :202, :228 and :246 are
  driven by a write to the WIPE_SECRET register and nothing else.
* The software error codes. `hmac.sv:852` `SwInvalidConfig`, :856
  `SwHashStartWhenShaDisabled`, :864 `SwPushMsgWhenDisallowed` and :868
  `SwUpdateSecretKeyInProcess`, with :829 `update_seckey_inprocess`. Each is a
  legal register access the design answers by setting ERR_CODE.

Stimulus, in three parts:

1. A keyed HMAC-SHA256 hash, split in two. Start it, push the first half of the
   message, stop it, read back DIGEST and MSG_LENGTH; then reprogram CFG, the
   key, the saved DIGEST and the saved MSG_LENGTH, continue, push the rest, and
   process. The same split is repeated at SHA2_384 and SHA2_512, whose 1024-bit
   block runs the wider `prim_sha2` datapath.
2. A write to WIPE_SECRET with a seeded value, followed by a plain SHA-256 hash
   so the wiped state is driven onward.
3. Four refused accesses, each followed by a read of ERR_CODE: a keyed start
   with KEY_LENGTH = 1024 against DIGEST_SIZE = SHA2_256, which
   `seq_lib/sep_hmac_seq.py` already derives as the one illegal keyed cell; a
   start with CFG.sha_en clear; a MSG_FIFO push while no hash is running; and a
   KEY write during a running hash.

ERR_CODE, STATUS, DIGEST and MSG_LENGTH are read and logged. Nothing read is
compared against an expectation: this leaf does not claim the restored context
reproduces the straight-through digest, only that the save and restore path was
driven. Every access is a legal register access answered with OKAY -- the design
reports its refusals in ERR_CODE, not as a bus error -- so no access here is
marked `allow_error`.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import HMAC
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_hmac_seq import (
    HMAC_CFG,
    HMAC_CMD,
    HMAC_DIGEST_0,
    HMAC_DIGEST_WORDS,
    HMAC_ERR_CODE,
    HMAC_INTR_STATE,
    HMAC_KEY_0,
    HMAC_MSG_FIFO,
    HMAC_STATUS,
    HMAC_STATUS_FIFO_FULL,
    HMAC_STATUS_IDLE,
    build_cfg,
)

HMAC_MSG_LENGTH_LOWER = HMAC.addr("MSG_LENGTH_LOWER")
HMAC_MSG_LENGTH_UPPER = HMAC.addr("MSG_LENGTH_UPPER")
HMAC_WIPE_SECRET = HMAC.addr("WIPE_SECRET")

CMD_HASH_START = HMAC.field_mask("CMD", "hash_start")
CMD_HASH_PROCESS = HMAC.field_mask("CMD", "hash_process")
CMD_HASH_STOP = HMAC.field_mask("CMD", "hash_stop")
CMD_HASH_CONTINUE = HMAC.field_mask("CMD", "hash_continue")

# (digest bits, key bits). 256 uses a 512-bit block, 384 and 512 a 1024-bit one,
# so the pair covers both prim_sha2 datapath widths.
SPLIT_CELLS = ((256, 256), (384, 512), (512, 512))

# Message words either side of the stop. Both halves are whole 512-bit blocks so
# the stop lands on a block boundary, which is where hmac_core.sv:381 takes it.
WORDS_PER_HALF = 32

# The one keyed cell the register specification blocks (sep_hmac_seq derives it
# from the block-size rule): KEY_LENGTH = 1024 with DIGEST_SIZE = SHA2_256.
ILLEGAL_SHA_BITS = 256
ILLEGAL_KEY_BITS = 1024

# Bounds on the STATUS polls. A hash of this size settles in far fewer reads;
# the caps keep a hash that never settles from spending the run timeout in one
# loop.
STATUS_POLLS = 400
POLL_GAP_CYCLES = 10


@pyuvm.test()
class sep_cov_hmac_stop_continue_test(sep_base_test):
    """HMAC stop/continue, wipe-secret and the software error codes. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.stim = SepCovStim(self)
        rng = SepSeededRng(self.random_seed())

        for sha_bits, key_bits in SPLIT_CELLS:
            await self._split_hash(rng, sha_bits, key_bits)

        await self._wipe_secret(rng)
        await self._error_walk(rng)

    # --- low-level helpers ---------------------------------------------------

    async def _wait_idle(self, tag: str) -> int:
        status = 0
        for _ in range(STATUS_POLLS):
            status = await self.stim._rd(HMAC_STATUS)
            if status & HMAC_STATUS_IDLE:
                return status
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: HMAC never reported idle at %s, continuing", tag)
        return status

    async def _push(self, words: list[int]) -> None:
        for word in words:
            for _ in range(STATUS_POLLS):
                if not (await self.stim._rd(HMAC_STATUS)) & HMAC_STATUS_FIFO_FULL:
                    break
                await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
            await self.stim._wr(HMAC_MSG_FIFO, word & 0xFFFF_FFFF)

    async def _read_digest(self, sha_bits: int) -> list[int]:
        return [
            await self.stim._rd(HMAC_DIGEST_0 + i * 4) for i in range(HMAC_DIGEST_WORDS[sha_bits])
        ]

    async def _clear_done(self) -> None:
        await self.stim._wr(HMAC_INTR_STATE, await self.stim._rd(HMAC_INTR_STATE))

    # --- part 1: stop and continue ------------------------------------------

    async def _split_hash(self, rng: SepSeededRng, sha_bits: int, key_bits: int) -> None:
        """Start a keyed hash, stop it on a block boundary, restore the saved
        context and finish it."""
        label = f"HMAC-SHA{sha_bits} key{key_bits}"
        cfg = build_cfg(hmac_en=True, sha_bits=sha_bits, key_bits=key_bits)
        key = [rng.getrandbits(32) for _ in range(key_bits // 32)]
        first = [rng.getrandbits(32) for _ in range(WORDS_PER_HALF)]
        second = [rng.getrandbits(32) for _ in range(WORDS_PER_HALF)]

        await self.stim._wr(HMAC_CFG, cfg)
        for i, word in enumerate(key):
            await self.stim._wr(HMAC_KEY_0 + i * 4, word)
        await self.stim._wr(HMAC_CMD, CMD_HASH_START)
        await self._push(first)
        await self.stim._wr(HMAC_CMD, CMD_HASH_STOP)
        await self._wait_idle(f"{label} stop")

        saved_digest = await self._read_digest(sha_bits)
        saved_len_lo = await self.stim._rd(HMAC_MSG_LENGTH_LOWER)
        saved_len_hi = await self.stim._rd(HMAC_MSG_LENGTH_UPPER)
        self.logger.info(
            "cov stimulus: %s stopped, MSG_LENGTH=0x%08x_%08x digest[0]=0x%08x, logged not graded",
            label,
            saved_len_hi,
            saved_len_lo,
            saved_digest[0],
        )
        await self._clear_done()

        # Restore: the configuration, the key, the intermediate digest and the
        # message length all go back before the continue command.
        await self.stim._wr(HMAC_CFG, cfg)
        for i, word in enumerate(key):
            await self.stim._wr(HMAC_KEY_0 + i * 4, word)
        for i, word in enumerate(saved_digest):
            await self.stim._wr(HMAC_DIGEST_0 + i * 4, word)
        await self.stim._wr(HMAC_MSG_LENGTH_LOWER, saved_len_lo)
        await self.stim._wr(HMAC_MSG_LENGTH_UPPER, saved_len_hi)
        await self.stim._wr(HMAC_CMD, CMD_HASH_CONTINUE)
        await self._push(second)
        await self.stim._wr(HMAC_CMD, CMD_HASH_PROCESS)
        await self._wait_idle(f"{label} process")
        final = await self._read_digest(sha_bits)
        self.logger.info(
            "cov stimulus: %s continued and processed, digest[0]=0x%08x, logged not graded",
            label,
            final[0],
        )
        await self._clear_done()

    # --- part 2: wipe secret -------------------------------------------------

    async def _wipe_secret(self, rng: SepSeededRng) -> None:
        await self.stim._wr(HMAC_WIPE_SECRET, rng.getrandbits(32))
        await self._wait_idle("post-wipe")
        cfg = build_cfg(hmac_en=False, sha_bits=256)
        await self.stim._wr(HMAC_CFG, cfg)
        await self.stim._wr(HMAC_CMD, CMD_HASH_START)
        await self._push([rng.getrandbits(32) for _ in range(WORDS_PER_HALF)])
        await self.stim._wr(HMAC_CMD, CMD_HASH_PROCESS)
        await self._wait_idle("post-wipe hash")
        self.logger.info("cov stimulus: WIPE_SECRET written and a plain SHA-256 run after it")
        await self._clear_done()

    # --- part 3: the software error codes ------------------------------------

    async def _log_err(self, label: str) -> None:
        err = await self.stim._rd(HMAC_ERR_CODE)
        self.logger.info("cov stimulus: %s -- ERR_CODE=0x%08x, logged not graded", label, err)

    async def _error_walk(self, rng: SepSeededRng) -> None:
        # A keyed start at the one cell the register specification blocks.
        await self.stim._wr(
            HMAC_CFG, build_cfg(hmac_en=True, sha_bits=ILLEGAL_SHA_BITS, key_bits=ILLEGAL_KEY_BITS)
        )
        await self.stim._wr(HMAC_CMD, CMD_HASH_START)
        await self._log_err("keyed start with KEY_LENGTH 1024 against SHA2_256")

        # A start with the SHA engine disabled. build_cfg clears sha_en together
        # with hmac_en only through this explicit word, so it is written here.
        await self.stim._wr(HMAC_CFG, 0)
        await self.stim._wr(HMAC_CMD, CMD_HASH_START)
        await self._log_err("start with CFG.sha_en clear")

        # A message push while no hash is running.
        await self.stim._wr(HMAC_CFG, build_cfg(hmac_en=False, sha_bits=256))
        await self._wait_idle("pre-push")
        await self.stim._wr(HMAC_MSG_FIFO, rng.getrandbits(32))
        await self._log_err("MSG_FIFO push while idle")

        # A key write during a running keyed hash.
        cfg = build_cfg(hmac_en=True, sha_bits=256, key_bits=256)
        key = [rng.getrandbits(32) for _ in range(8)]
        await self.stim._wr(HMAC_CFG, cfg)
        for i, word in enumerate(key):
            await self.stim._wr(HMAC_KEY_0 + i * 4, word)
        await self.stim._wr(HMAC_CMD, CMD_HASH_START)
        await self.stim._wr(HMAC_KEY_0, rng.getrandbits(32))
        await self._log_err("KEY write during a running hash")
        await self.stim._wr(HMAC_CMD, CMD_HASH_PROCESS)
        await self._wait_idle("error-walk tail")
        await self._clear_done()
