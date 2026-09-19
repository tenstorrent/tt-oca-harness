# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV AES known-answer firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_aes: one AES-128 ECB encryption against a
fixed vector, compared on-chip, with the alert status checked before the image
parks. The verdict is the firmware's own.

The vector is the one smu_sep_modules_test's AES stage also runs (the two
images share the key, plaintext and expected ciphertext); what this leaf adds
is the cipher in isolation from the HMAC and KMAC stages, on a dedicated image
whose only subject is AES, with the alert status checked before it parks.

AES masking reseeds its PRNG from crypto-EDN, so the image brings the entropy
stack up first and parks in a distinct fail loop if that does not complete --
the prerequisite and the cipher stay separately attributable. The ring
oscillators do not self-oscillate under Verilator, so +esrc_noise_force has to
supply the raw noise; see seq_lib/esrc_noise.py.
"""

from __future__ import annotations

import cocotb

from seq_lib.esrc_noise import SmuEsrcNoiseDriver
from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepAesSeq(SepTerminalLoopSeq):
    NAME = "sep_aes"
    PASS_SYM = "smu_sep_aes_pass_loop"
    FAIL_SYMS = {
        "aes": "smu_sep_aes_fail_loop",
        # Prerequisite rather than cipher: a bring-up that never completed lands
        # here, so it is not reported as an AES failure.
        "entropy": "smu_sep_aes_fail_entropy_loop",
    }
    SYM_DEFAULT = "sep_smu_aes.tcm.sym"
    # The image waits out the ESRC boot health-test window (2048 samples at
    # div64, ~131k core cycles) before the masking PRNG can reseed, so the budget
    # has to clear that with margin; the KAT itself is a few thousand cycles.
    MAX_CYCLES_DEFAULT = 600_000
    EVIDENCE = ("SEP_REAL_FW_AES_OK", "SEP_AES_ECB128_KAT_OK")

    async def run(self) -> None:
        assert cocotb.plusargs.get("esrc_noise_force") is not None, (
            "+esrc_noise_force is required: without driven noise the image's "
            "entropy bring-up stalls at the ESRC boot gate and never reaches "
            "the cipher at all"
        )
        SmuEsrcNoiseDriver(self.dut).start()
        await super().run()
