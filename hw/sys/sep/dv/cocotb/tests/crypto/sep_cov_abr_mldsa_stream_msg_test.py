# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ML-DSA KEYGEN+SIGN with a streamed message and a non-empty context.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. The signature this leaf produces is never read back or compared,
and the key material is arbitrary: the point is that the engine runs.

Target, against the merged VCS run ``build/runs/20260919_225443__vcs__all``:

* ``abr_ctrl`` FSM ``stream_msg_fsm_ps`` reports 1 of 6 states covered and 0 of
  10 transitions. The whole block at ``abr_ctrl.sv:1862`` (the ``unique case``
  over that FSM) scores 10 of 31 lines, and its ``CASE 1870`` branch scores 2
  of 15. The three ML-DSA KAT leaves use the ACVP external-mu vector groups, so
  they set ``MLDSA_CTRL.EXTERNAL_MU`` and write mu into
  ``MLDSA_EXTERNAL_MU``; ``stream_msg_mode`` (``abr_ctrl.sv:757``) is never
  set and the FSM never leaves ``MLDSA_MSG_IDLE``. That is why the streaming
  path is dark, not a missing operation -- the datapath modules those KATs
  drive (``ntt_top``, ``skdecode_top``, ``sigdecode_z_top``, ``compress_top``,
  ``decompose``, ``power2round_top``) are all at 100% line already.
* ``MLDSA_CTRL.CTRL`` command ``KEYGEN_SIGN`` (0x4) is one of the two
  program-counter entry points in the ``ABR_RESET`` case no leaf issues, and it
  is also the only way to reach the taken leg of ``MLDSA_KG_JUMP_SIGN``
  (``abr_ctrl.sv:1715``).
* Internal-mu signing reaches the ``MLDSA_SIGN_H_MU`` leg of
  ``MLDSA_SIGN_CHECK_MODE`` (``abr_ctrl.sv:1729``), which the external-mu KAT
  cannot, and the ``stream_msg_mode`` leg of ``msg_p_reg``
  (``abr_ctrl.sv:1342``).
* ``MLDSA_CTX_CONFIG``, ``MLDSA_CTX`` and ``MLDSA_MSG_STROBE`` are read by the
  hardware here rather than only written, so ``ctx_reg`` and the strobe move as
  engine inputs. ``sep_cov_abr_reg_walk_test`` covers their register-file write
  legs; this leaf covers the consumer.

Programming order. ``MLDSA_CTRL``, ``MLDSA_SEED``, ``ABR_ENTROPY``,
``MLDSA_SIGN_RND``, ``MLDSA_CTX_CONFIG`` and ``MLDSA_CTX`` are all
``swwe = abr_ready`` in ``abr_reg.rdl``, so every input is written while the
core is idle and ``MLDSA_CTRL`` is written last, because that write is what
starts the operation. ``MLDSA_MSG_STROBE`` is the exception: its gate is
``stream_msg_rdy``, so it can only be written from inside the streaming window,
which is what ``MLDSA_STATUS.MSG_STREAM_READY`` publishes.

RANDCFG: the seed, masking entropy, signing randomness, context bytes, message
words and the final byte strobe all come from the run seed through
``SepSeededRng``. None of them is a key, nonce or token, and nothing leaves the
simulation.

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
    ABR_SIGN_RND,
    ABR_STATUS,
    CTRL_ZEROIZE,
    ENTROPY_WORDS,
    SEED_WORDS,
    ST_READY,
    ST_VALID,
)
from seq_lib.sep_cov_abr_op_seq import (
    CMD_KEYGEN_SIGN,
    CTRL_STREAM_MSG,
    SIGN_RND_WORDS,
    TAIL_STROBES,
    SepCovAbrOp,
)

# Context byte count. 9 is deliberately not a multiple of four: MLDSA_MSG_CTX
# splits ctx_size into ctx_cnt_required (9 >> 2 = 2) and ctx_cnt_offset
# (9 & 3 = 1), so the state runs three beats and the last one carries a partial
# strobe. A multiple of four would leave the partial-strobe ternary at
# abr_ctrl.sv:1884 one-sided.
CTX_SIZE_BYTES = 9
CTX_BEAT_WORDS = 3

# Streamed message length in full 32-bit beats, before the partial tail beat.
# Long enough that the MLDSA_MSG_RDY state is re-entered many times and short
# enough that the stream is not the dominant cost of the run.
MSG_BEATS = 12


@pyuvm.test()
class sep_cov_abr_mldsa_stream_msg_test(sep_base_test):
    """ML-DSA KEYGEN+SIGN, internal mu, message streamed with a context."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        seed = [rng.getrandbits(32) for _ in range(SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        sign_rnd = [rng.getrandbits(32) for _ in range(SIGN_RND_WORDS)]
        ctx = [rng.getrandbits(32) for _ in range(CTX_BEAT_WORDS)]
        msg = [rng.getrandbits(32) for _ in range(MSG_BEATS)]
        tail_strobe = TAIL_STROBES[rng.randrange(len(TAIL_STROBES))]
        tail_word = rng.getrandbits(32)

        await self.bring_up_no_cpu()
        abr = SepCovAbrOp(self)

        await abr.poll_status(ABR_STATUS, ST_READY, ST_READY, what="pre-command READY")

        await abr.write_words(ABR_SEED, seed)
        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.write_words(ABR_SIGN_RND, sign_rnd)
        await abr.write_ctx(CTX_SIZE_BYTES, ctx)

        await abr.wr32(ABR_CTRL, CMD_KEYGEN_SIGN | CTRL_STREAM_MSG)
        self.logger.info(
            "cov stimulus: MLDSA_CTRL=0x%02x (KEYGEN_SIGN | STREAM_MSG), ctx_size=%d bytes",
            CMD_KEYGEN_SIGN | CTRL_STREAM_MSG,
            CTX_SIZE_BYTES,
        )

        beats = await abr.stream_message(msg, tail_strobe, tail_word)
        self.logger.info(
            "cov stimulus: streamed %d message beats, tail strobe 0b%04b", beats, tail_strobe
        )

        await abr.poll_status(ABR_STATUS, ST_VALID, ST_VALID, what="keygen+sign VALID")
        self.logger.info("cov stimulus: KEYGEN_SIGN reached VALID over the streamed message")

        # ZEROIZE returns the core to READY and drops the streaming-mode field,
        # so the run leaves the engine idle for whatever shares the build.
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await abr.poll_status(ABR_STATUS, ST_READY, ST_READY, what="post-zeroize READY")
        self.logger.info("cov stimulus: ABR ML-DSA stream-message path driven")
