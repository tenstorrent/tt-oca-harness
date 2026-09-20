# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run AES at every key length in both directions, then clear the key, the IV,
the input and the output through the TRIGGER register.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `aes_key_expand` holds 58 uncovered lines and `aes_cipher_control_fsm`
32 in the merged VCS run `build/runs/20260919_225443__vcs__all`. Three separate
gaps account for them, and all three are selected from AES CSRs:

* The AES-192 key schedule. `hw/sys/sep/rtl/aes_wrapper.sv:134` overrides no
  parameter, so `AES192Enable` keeps its default of 1
  (`vendor/lowRISC/opentitan/upstream/hw/ip/aes/rtl/aes.sv:15`) and the
  `if (AES192Enable)` arms at
  `vendor/lowRISC/opentitan/upstream/hw/ip/aes/rtl/aes_key_expand.sv:156` and
  :335 elaborate. `rnd_type` (:71-74), the 192-bit rotate-word cases (:159-167)
  and the 192-bit regular-word cases (:338-376) are dark only because no leaf
  selects CTRL_SHADOWED.KEY_LEN = AES_192.
* Decryption. `aes_key_expand.sv:145-148` and :311-324 are the `CIPH_INV` arms
  of the rotate and regular word muxes, and
  `vendor/lowRISC/opentitan/upstream/hw/ip/aes/rtl/aes_cipher_control_fsm.sv:303-313`
  is the decryption key-generation pass (`key_dec_we_o`,
  `dec_key_gen_d_o`). They need CTRL_SHADOWED.OPERATION = AES_DEC.
* The clear states. `aes_cipher_control_fsm.sv:400-425` is
  `CIPHER_CTRL_CLEAR_S` and `CIPHER_CTRL_CLEAR_KD`, entered from the
  KEY_IV_DATA_IN_CLEAR and DATA_OUT_CLEAR triggers, and :385-394 is
  `CIPHER_CTRL_PRNG_RESEED`. `seq_lib/sep_aes_seq.py` pulses DATA_OUT_CLEAR
  alone, which does not reach the key and key-decryption clear at :407-411.

Stimulus: one ECB session per (key length, operation) cell -- 128, 192 and 256
bits, encrypt and decrypt -- each loading a fresh seeded key and running two
blocks, followed by one CBC cell at 192 bits so the key schedule runs against a
chained IV as well. Then the TRIGGER register is pulsed for PRNG_RESEED,
KEY_IV_DATA_IN_CLEAR and DATA_OUT_CLEAR, with STATUS polled back to idle
between them.

The ciphertext of an encrypt cell is not fed to the matching decrypt cell and no
output is compared: this leaf does not claim AES round-trips, only that the key
schedule and the clear states were driven.

AES masking stalls without entropy, so the run brings up the real
ESRC/DRBG/CSRNG/EDN stack first, in the stimulus-only order that
`tests/crypto/sep_cov_aes_gcm_phase_walk_test.py` uses.

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES
from seq_lib.sep_aes_seq import (
    AES_KEY_LEN_128,
    AES_KEY_LEN_192,
    AES_KEY_LEN_256,
    AES_MODE_CBC,
    AES_MODE_ECB,
    AES_OP_DEC,
    AES_OP_ENC,
    AES_TRIGGER,
    SepAes,
)
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)

# TRIGGER field masks, from the generated AES_TRIGGER bitfield.
TRIGGER_KEY_IV_DATA_IN_CLEAR = AES.field_mask("TRIGGER", "key_iv_data_in_clear")
TRIGGER_DATA_OUT_CLEAR = AES.field_mask("TRIGGER", "data_out_clear")
TRIGGER_PRNG_RESEED = AES.field_mask("TRIGGER", "prng_reseed")

# (label, CTRL_SHADOWED.KEY_LEN encoding, SW key words). aes_pkg.sv:131-133
# encodes the key length one-hot; the word count is the key width / 32.
KEY_CELLS = (
    ("128", AES_KEY_LEN_128, 4),
    ("192", AES_KEY_LEN_192, 6),
    ("256", AES_KEY_LEN_256, 8),
)

OPERATIONS = (("enc", AES_OP_ENC), ("dec", AES_OP_DEC))

BLOCKS_PER_CELL = 2
WORDS_PER_BLOCK = 4


@pyuvm.test()
class sep_cov_aes_key192_dec_clear_test(sep_base_test):
    """AES key lengths, both directions, and the clear triggers. Stimulus only."""

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

            aes = SepAes(self)
            rng = SepSeededRng(self.random_seed())
            await aes.trigger_prng_reseed()

            for label, key_len, key_words in KEY_CELLS:
                for op_name, operation in OPERATIONS:
                    await self._cell(
                        aes,
                        rng,
                        f"ECB-{label} {op_name}",
                        AES_MODE_ECB,
                        key_len,
                        key_words,
                        operation,
                    )

            await self._cell(
                aes, rng, "CBC-192 enc", AES_MODE_CBC, AES_KEY_LEN_192, 6, AES_OP_ENC, iv=True
            )
            await self._cell(
                aes, rng, "CBC-192 dec", AES_MODE_CBC, AES_KEY_LEN_192, 6, AES_OP_DEC, iv=True
            )

            await self._clear_walk(aes)
        finally:
            noise.kill()

    async def _cell(
        self,
        aes: SepAes,
        rng: SepSeededRng,
        label: str,
        mode: int,
        key_len: int,
        key_words: int,
        operation: int,
        *,
        iv: bool = False,
    ) -> None:
        """Configure one key length / mode / direction and run two blocks."""
        await aes.configure(mode=mode, key_len=key_len, operation=operation)
        key = [rng.getrandbits(32) for _ in range(key_words)]
        iv_words = [rng.getrandbits(32) for _ in range(4)] if iv else None
        await aes.load_key_iv(key, iv_words)
        data = [rng.getrandbits(32) for _ in range(BLOCKS_PER_CELL * WORDS_PER_BLOCK)]
        out = await aes.run_blocks(data)
        self.logger.info(
            "cov stimulus: %s produced %d words (first 0x%08x), logged not graded",
            label,
            len(out),
            out[0] if out else 0,
        )

    async def _clear_walk(self, aes: SepAes) -> None:
        """Pulse each TRIGGER clear in turn, waiting idle between them."""
        for mask, label in (
            (TRIGGER_PRNG_RESEED, "PRNG_RESEED"),
            (TRIGGER_KEY_IV_DATA_IN_CLEAR, "KEY_IV_DATA_IN_CLEAR"),
            (TRIGGER_DATA_OUT_CLEAR, "DATA_OUT_CLEAR"),
            (
                TRIGGER_KEY_IV_DATA_IN_CLEAR | TRIGGER_DATA_OUT_CLEAR,
                "KEY_IV_DATA_IN_CLEAR + DATA_OUT_CLEAR together",
            ),
        ):
            await aes._wr(AES_TRIGGER, mask)
            await aes.wait_idle(f"post-{label}")
            self.logger.info("cov stimulus: TRIGGER %s pulsed", label)
