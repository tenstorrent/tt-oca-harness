# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Absorb message lengths that land the SHA-3 pad byte on the last word of a
Keccak block, which is the only way into the sha3pad StPadRun state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No digest is read back for comparison.

Target, `vendor/lowRISC/opentitan/upstream/hw/ip/kmac/rtl/sha3pad.sv`. The
StPad case at :390 takes two exits:

* `keccak_ack && end_of_block` -> StPadRun (:422), then StPadRun -> StPadFlush
  (:436) unconditionally.
* `keccak_ack` alone -> StPad01 (:428).

`end_of_block` (:288) is `(sent_message + 1) == block_addr_limit`, so the first
exit needs the padding beat to be the last 64-bit word of the block. That
happens only when the message ends exactly one word short of the Keccak rate.
Every KMAC leaf in the suite absorbs a length chosen for its vector, none of
which is rate-aligned in that way, so StPadRun and both of its arcs are dark.

The lengths below are rate - 8 bytes for each strength: SHAKE-128's rate is
168 bytes (21 words of 64 bits), SHAKE-256's is 136 bytes (17 words). One
neighbour on each side is absorbed too, so the run still drives the StPad01
exit from the same configuration and a mis-modelled rate does not silently
leave the target unreached.

KMAC masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first.

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
    KMAC_MODE,
    KMAC_MSG_FIFO,
    KMAC_STATUS,
    KMAC_STATUS_IDLE,
    KMAC_STATUS_SQUEEZE,
    KMAC_STRENGTH,
    SepKmac,
    build_kmac_cfg,
)

# Keccak rates in bytes, from the sponge capacity of each strength.
RATE_BYTES = {128: 168, 256: 136}

# The pad beat is a 64-bit Keccak word, so the block-aligned case is the
# message that stops exactly one word short of the rate.
PAD_WORD_BYTES = 8

# One neighbour each side, in 32-bit MSG_FIFO words, so the same configuration
# also drives the StPad -> StPad01 exit.
NEIGHBOUR_OFFSET_WORDS = (-1, 0, 1)

STATUS_POLLS = 600
POLL_GAP_CYCLES = 20


@pyuvm.test()
class sep_cov_kmac_pad_block_aligned_test(sep_base_test):
    """Rate-aligned SHA-3 padding, for the sha3pad StPadRun arc. Stimulus only."""

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
            for strength, rate in RATE_BYTES.items():
                aligned_words = (rate - PAD_WORD_BYTES) // 4
                for delta in NEIGHBOUR_OFFSET_WORDS:
                    await self._absorb(rng, strength, aligned_words + delta)
        finally:
            noise.kill()

    async def _poll(self, mask: int, label: str) -> int:
        status = 0
        for _ in range(STATUS_POLLS):
            status = await self.kmac._rd(KMAC_STATUS)
            if status & mask:
                return status
            await ClockCycles(cocotb.top.clk_i, POLL_GAP_CYCLES)
        self.logger.info("cov stimulus: KMAC STATUS bit not seen at %s, continuing", label)
        return status

    async def _absorb(self, rng: SepSeededRng, strength: int, msg_words: int) -> None:
        cfg = build_kmac_cfg(
            mode=KMAC_MODE["shake"], kstrength=KMAC_STRENGTH[strength], kmac_en=False
        )
        # CFG_SHADOWED is shadowed: the value must be written twice.
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self.kmac._wr(KMAC_CFG_SHADOWED, cfg)
        await self._poll(KMAC_STATUS_IDLE, f"pre-start shake{strength}")

        await self.kmac._wr(KMAC_CMD, KMAC_CMD_START)
        for _ in range(msg_words):
            await self.kmac._wr(KMAC_MSG_FIFO, rng.getrandbits(32))
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_PROCESS)
        await self._poll(KMAC_STATUS_SQUEEZE, f"absorb shake{strength} {msg_words}w")
        await self.kmac._wr(KMAC_CMD, KMAC_CMD_DONE)
        await self._poll(KMAC_STATUS_IDLE, f"post-done shake{strength} {msg_words}w")

        self.logger.info(
            "cov stimulus: SHAKE-%d absorbed %d message bytes against a %d-byte rate "
            "(%+d word from the block-aligned pad)",
            strength,
            msg_words * 4,
            RATE_BYTES[strength],
            msg_words - (RATE_BYTES[strength] - PAD_WORD_BYTES) // 4,
        )
