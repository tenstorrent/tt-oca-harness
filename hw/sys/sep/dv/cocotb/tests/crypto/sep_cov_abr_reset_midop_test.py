# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hold the Adams Bridge engine in per-IP software reset while an ML-DSA or
ML-KEM command is running, so its sub-FSMs return to idle from a running state.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. No key, signature or digest is read back or compared.

Target: the FSM arcs whose destination is the FSM's own reset state and which
no `case` arm assigns anywhere. In the ABR hierarchy those are, per FSM:

* `abr_ctrl.sv` `abr_ctrl_fsm_ns` -- 6 arcs into ABR_CTRL_IDLE, and
  `stream_msg_fsm_ns` -- 5 arcs into MLDSA_MSG_IDLE.
* `abr_sha3/rtl/abr_keccak_round.sv` -- 11, `abr_sha3.sv` -- 2,
  `abr_sha3pad.sv` -- 7.
* `abr_sampler_top.sv` -- 3, `ntt_top/rtl/ntt_ctrl.sv` -- 6,
  `makehint/rtl/makehint.sv` -- 5, `pk_decode/rtl/pkdecode.sv` -- 2,
  `power2round/rtl/power2round_ctrl.sv` -- 4,
  `sample_in_ball/rtl/sample_in_ball_ctrl.sv` -- 2,
  `sigdecode_h/rtl/sigdecode_h_ctrl.sv` -- 3,
  `sig_decode_z/rtl/sigdecode_z_top.sv` -- 2,
  `sig_encode_z/rtl/sigencode_z_top.sv` -- 2,
  `sk_decode/rtl/skdecode_ctrl.sv` -- 5, `sk_encode/rtl/skencode.sv` -- 5.

The sibling leaf `sep_cov_abr_zeroize_midabsorb_test` drives the same blocks
mid-operation with ZEROIZE, which the `case` arms do assign. A reset is the
only stimulus that takes the arcs above, because the state flop's reset value
is what performs the assignment.

Mechanism: `SW_RESET_N.abr_sw_rst_n` (`sep_reset_ctrl.sv:136`). Clearing it
raises `abr_isolate_req` (:155-161), `sep_isolate_rst_seq` waits for the ABR
host and KM AXI ports to isolate, and then drops `isolated_rst_n.abr`, which
becomes the ABR wrapper `rst_ni`. The same pulse also drives
`sep_isolate_rst_seq`'s own 4 reset arcs.

The ABR engine is not an EDN client: `sep_crypto.sv:429-477` wires the four
`crypto_edn_req` slots to OTBN RND, OTBN URND, AES and KMAC only. So an ABR
reset cannot drop an ungranted `edn_req` on the crypto entropy arbiter, and
this leaf needs no entropy bring-up.

Randomness: the reset offsets come from `SepSeededRng` seeded with the run
seed, so `--stage sim --seed N` replays a given landing point. They are not a
key, nonce or token, and nothing derived from them leaves the simulation.

Safety: the ABR bit is released after every pulse and `SW_RESET_N` is restored
in a `finally`, so no later leaf inherits a held engine.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
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
from seq_lib.sep_cov_reset_arc_seq import SepCovEngineReset

MLDSA_SEED_WORDS = 8

# Offsets, in core clock cycles after the command write, at which the reset
# request is raised. A keygen runs for thousands of cycles and walks the
# sampler, NTT, keccak and encode/decode blocks in turn, so a spread this wide
# lands the reset in a different set of states on each pass. Which state a
# given offset hits is not claimed: this is stimulus, not a check.
RESET_DELAY_MIN = 40
RESET_DELAY_MAX = 6_000
RESETS_PER_ENGINE = 10


@pyuvm.test()
class sep_cov_abr_reset_midop_test(sep_base_test):
    """Per-IP reset inside a running ABR command. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        self.abr = SepCovAbrOp(self)
        rst = SepCovEngineReset(self, "abr")

        try:
            await self.abr.poll_status(
                ABR_STATUS, ST_READY, ST_READY, what="pre-run ML-DSA READY"
            )
            for idx in range(RESETS_PER_ENGINE):
                await self._reset_mldsa(rng, rst, idx)
            for idx in range(RESETS_PER_ENGINE):
                await self._reset_mlkem(rng, rst, idx)
        finally:
            await rst.restore()

        self.logger.info(
            "COV-STIM abr_reset_midop: %d per-IP resets driven inside a running "
            "ML-DSA or ML-KEM keygen",
            rst.pulses,
        )

    async def _reset_mldsa(self, rng, rst: SepCovEngineReset, idx: int) -> None:
        seed = [rng.getrandbits(32) for _ in range(MLDSA_SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)

        await self.abr.write_words(ABR_SEED, seed)
        await self.abr.write_words(ABR_ENTROPY, entropy)
        await self.abr.wr32(ABR_CTRL, CMD_KEYGEN)

        await rst.pulse(delay_cycles=delay, tag=f"mldsa_keygen_{idx}")

        # Back to a known start point for the next pass: the reset already
        # cleared the datapath, ZEROIZE returns the register file, and the
        # poll is flow control on the engine's own READY bit.
        await self.abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self.abr.poll_status(
            ABR_STATUS, ST_READY, ST_READY, what=f"ML-DSA post-reset {idx} READY"
        )

    async def _reset_mlkem(self, rng, rst: SepCovEngineReset, idx: int) -> None:
        seed_d = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        seed_z = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        delay = rst.delay(rng, RESET_DELAY_MIN, RESET_DELAY_MAX)

        await self.abr.write_words(MLKEM_SEED_D, seed_d)
        await self.abr.write_words(MLKEM_SEED_Z, seed_z)
        await self.abr.write_words(ABR_ENTROPY, entropy)
        await self.abr.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)

        await rst.pulse(delay_cycles=delay, tag=f"mlkem_keygen_{idx}")

        await self.abr.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self.abr.poll_status(
            MLKEM_STATUS, KEM_ST_READY, KEM_ST_READY, what=f"ML-KEM post-reset {idx} READY"
        )
