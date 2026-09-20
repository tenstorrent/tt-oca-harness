# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroize an Adams Bridge operation at a randomized point inside its SHAKE
absorb, so abr_sha3pad returns to idle from each of its running states.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No key, signature or digest is read back or compared.

Target,
`vendor/chipsalliance/adams-bridge/upstream/src/abr_sha3/rtl/abr_sha3pad.sv:487`:

    if (zeroize) st_d = StPadIdle;

That line is the only source of the StMessage, StPad, StPad01 and StPadRun
returns to StPadIdle. The StPadFlush return at :466 is the one the case bodies
provide, and it is the one the suite already covers: every ML-DSA and ML-KEM
leaf runs its command to VALID and only then writes ZEROIZE, by which time the
pad FSM is already idle.

The difference here is only the timing: ZEROIZE is written while the command is
still running, after a seeded delay. The delay is swept over a spread of values
so the write lands in a different pad state on each iteration.

`MLDSA_CTRL.ZEROIZE` and `MLKEM_CTRL.ZEROIZE` are the architected way to abandon
an operation, so this is a legal frontdoor sequence and every access is answered
with OKAY. Each iteration ends with a ZEROIZE from the settled state and a poll
back to READY, so an iteration cannot leave the engine busy for the next one.

RANDCFG: the seeds, the masking entropy and the abort delays all come from the
run seed through `SepSeededRng`. None of them is a key, nonce or token, and
nothing leaves the simulation.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_SEED,
    ABR_STATUS,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    ENTROPY_WORDS,
    ST_READY,
)
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_KEYGEN,
    KEM_CTRL_ZEROIZE,
    KEM_SEED_WORDS,
    KEM_ST_READY,
    MLKEM_CTRL,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_STATUS,
)
from seq_lib.sep_cov_abr_op_seq import SepCovAbrOp

MLDSA_SEED_WORDS = 8

# The abort delays, in core clock cycles after the command write. The SHAKE
# absorb of a keygen runs for thousands of cycles, and the pad FSM cycles
# through message, pad and flush many times inside it, so a spread this wide
# lands the abort in a different pad state on each pass. The exact state a
# given delay hits is not claimed: this is stimulus, not a check.
ABORT_DELAY_MIN = 40
ABORT_DELAY_MAX = 6_000
ABORTS_PER_ENGINE = 12


@pyuvm.test()
class sep_cov_abr_zeroize_midabsorb_test(sep_base_test):
    """ZEROIZE inside a running ABR command. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        self.abr = SepCovAbrOp(self)

        await self.abr.poll_status(ABR_STATUS, ST_READY, ST_READY, what="pre-run ML-DSA READY")
        for idx in range(ABORTS_PER_ENGINE):
            await self._abort_mldsa(rng, idx)
        for idx in range(ABORTS_PER_ENGINE):
            await self._abort_mlkem(rng, idx)

    def _delay(self, rng: SepSeededRng) -> int:
        span = ABORT_DELAY_MAX - ABORT_DELAY_MIN
        return ABORT_DELAY_MIN + (rng.getrandbits(32) % (span + 1))

    async def _abort_mldsa(self, rng: SepSeededRng, idx: int) -> None:
        seed = [rng.getrandbits(32) for _ in range(MLDSA_SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        delay = self._delay(rng)

        await self.abr.write_words(ABR_SEED, seed)
        await self.abr.write_words(ABR_ENTROPY, entropy)
        await self.abr.wr32(ABR_CTRL, CMD_KEYGEN)

        await ClockCycles(cocotb.top.clk_i, delay)
        await self.abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        self.logger.info(
            "cov stimulus: ML-DSA keygen %d aborted with ZEROIZE %d cycles in", idx, delay
        )

        await self.abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self.abr.poll_status(
            ABR_STATUS, ST_READY, ST_READY, what=f"ML-DSA post-abort {idx} READY"
        )

    async def _abort_mlkem(self, rng: SepSeededRng, idx: int) -> None:
        seed_d = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        seed_z = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        delay = self._delay(rng)

        await self.abr.write_words(MLKEM_SEED_D, seed_d)
        await self.abr.write_words(MLKEM_SEED_Z, seed_z)
        await self.abr.write_words(ABR_ENTROPY, entropy)
        await self.abr.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)

        await ClockCycles(cocotb.top.clk_i, delay)
        await self.abr.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        self.logger.info(
            "cov stimulus: ML-KEM keygen %d aborted with ZEROIZE %d cycles in", idx, delay
        )

        await self.abr.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self.abr.poll_status(
            MLKEM_STATUS, KEM_ST_READY, KEM_ST_READY, what=f"ML-KEM post-abort {idx} READY"
        )
