# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ML-KEM KEYGEN+DECAPS, the combined command no leaf issues.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. The shared key is never read back or compared, and the
ciphertext is arbitrary: FIPS-203 implicit rejection means a ciphertext that
does not decapsulate still produces a shared key rather than an error, so the
engine runs the full program either way.

Target, against the merged VCS run ``build/runs/20260919_225443__vcs__all``:

* ``MLKEM_CTRL.CTRL`` command ``KEYGEN_DECAPS`` (0x4) is one of the two
  program-counter entry points in the ``ABR_RESET`` case of ``abr_ctrl`` that
  no leaf issues (``abr_ctrl.sv:1695``). ``sep_abr_mlkem_kat_test`` walks
  KEYGEN, ENCAPS and DECAPS as three separate commands and says so in its own
  docstring; the combined command is a different arc.
* It is also the only way to reach the taken leg of ``MLKEM_KG_E``
  (``abr_ctrl.sv:1758``), which jumps the program counter straight from the
  end of keygen into ``MLKEM_DECAPS_S`` instead of raising
  ``mlkem_keygen_done``. Those legs sit in the ``abr_ctrl.sv:1627`` block,
  which scores 77 of 94 lines, and in ``CASE 1650``, which scores 23 of 30
  branches.
* ``MLKEM_SEED_Z`` is written as an engine input rather than as a register
  walk, so the seed lane toggles with real data.

Programming order. ``MLKEM_CTRL`` is ``swwe = abr_ready`` in ``abr_reg.rdl``,
so a command written to a busy engine is dropped silently and the previous
VALID still reads back. Every input is written while READY is set and
``MLKEM_CTRL`` is written last.

RANDCFG: both seeds, the masking entropy and the ciphertext come from the run
seed through ``SepSeededRng``. None of them is a key, nonce or token, and
nothing leaves the simulation.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import ABR_ENTROPY, ENTROPY_WORDS
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_KEYGEN_DECAPS,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_SEED_WORDS,
    KEM_ST_READY,
    KEM_ST_VALID,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_STATUS,
)
from seq_lib.sep_cov_abr_op_seq import SepCovAbrOp


@pyuvm.test()
class sep_cov_abr_mlkem_keygen_decaps_test(sep_base_test):
    """ML-KEM-1024 KEYGEN+DECAPS as one command. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        seed_d = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        seed_z = [rng.getrandbits(32) for _ in range(KEM_SEED_WORDS)]
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        ciphertext = [rng.getrandbits(32) for _ in range(KEM_CT_WORDS)]

        await self.bring_up_no_cpu()
        abr = SepCovAbrOp(self)

        await abr.poll_status(MLKEM_STATUS, KEM_ST_READY, KEM_ST_READY, what="pre-command READY")

        await abr.write_words(MLKEM_SEED_D, seed_d)
        await abr.write_words(MLKEM_SEED_Z, seed_z)
        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.write_words(MLKEM_CIPHERTEXT, ciphertext)

        await abr.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN_DECAPS)
        self.logger.info(
            "cov stimulus: MLKEM_CTRL=0x%02x (KEYGEN_DECAPS) over a %d-word ciphertext",
            KEM_CMD_KEYGEN_DECAPS,
            KEM_CT_WORDS,
        )

        await abr.poll_status(MLKEM_STATUS, KEM_ST_VALID, KEM_ST_VALID, what="keygen+decaps VALID")
        self.logger.info("cov stimulus: KEYGEN_DECAPS ran keygen through to decaps and set VALID")

        # ZEROIZE returns the core to READY, so the run leaves the engine idle
        # for whatever shares the build.
        await abr.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await abr.poll_status(MLKEM_STATUS, KEM_ST_READY, KEM_ST_READY, what="post-zeroize READY")
        self.logger.info("cov stimulus: ABR ML-KEM combined keygen+decaps path driven")
