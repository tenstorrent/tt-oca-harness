# SPDX-License-Identifier: Apache-2.0
"""Standalone AES mode x key-size breadth, RAND-REP (AES mode/key-size breadth).

Drives the OpenTitan AES engine directly over the CPU-LSU AXI master (no_cpu, no
firmware, SW key) across the full standalone matrix the Phase-1 KM->AES sideload
KAT (#11, ECB-256 via keymgr) does not reach:

    {ECB, CBC, CTR} x {128, 192, 256}  (9 cells).

OCAH parity: MERGED_INTO rep of the OCAH aes mode/keylen directed set. The OCAH
uvm_tests/aes suite is register/alert-centric with no standalone CBC/CTR/128/192
ciphertext golden, so the independent pure-Python golden (env/sep_aes_golden.py:
FIPS-197 ECB 128/192/256 + SP800-38A CBC/CTR self-tested) is the reference and
this rep is stronger-than-OCAH for encryption breadth. DISTINCT from #11 (ECB-256
via sideload) -- AES mode/key-size breadth is standalone SW-key across modes/sizes.

Entropy: OpenTitan AES masking reseeds its PRNG from the crypto-EDN leg, so the
test brings up the real ESRC->DRBG->EDN stack (+esrc_noise_force) before any AES
op or the engine stalls. The DRBG scoreboard runs non-strict (AES mode/key-size breadth's contract is
AES correctness, not the entropy golden -- that is #15/KMAC mode/strength breadth/crypto-EDN multisink arbitration); simply
reaching the ciphertext checks proves masking entropy flowed (CHK-ENTROPY).

RAND-REP contract (AGENTS.md §9): a SepAesCfg config object is the single source
of truth for BOTH DUT programming (CTRL + key + IV + data) AND the golden. The 9
discrete (mode, key-size) cells are WALKED DETERMINISTICALLY in one invocation;
the seed randomizes only the legal continuous knobs (key, IV, plaintext content).

Checkers:
  CHK-ENC      per cell: engine ciphertext == independent golden (2 blocks)
  CHK-RT       per cell: round-trip recovers plaintext -- ECB/CBC via engine
               DECRYPT, CTR via re-encrypt (stream self-inverse)
  CHK-STATUS   per cell: no AES recoverable/fatal alert across enc + round-trip
  CHK-NONVAC   per cell: ciphertext != plaintext and != wrong-key golden
  CHK-ENTROPY  masking-PRNG reseed completed (reaching CHK-ENC is the evidence)
  CHK-RAND-REP all 9 discrete cells walked in one invocation (seed logged)
"""

from __future__ import annotations

import random

import pyuvm

from sep_base_test import sep_base_test
from env.sep_aes_golden import aes_encrypt_words
from seq_lib.sep_aes_seq import SepAes, SepAesCfg, AES_OP_ENC, AES_OP_DEC

MODES = ["ecb", "cbc", "ctr"]
KEY_SIZES = [128, 192, 256]
NUM_BLOCKS = 2   # 2 x 128-bit blocks per cell -> exercises CBC chaining / CTR increment


@pyuvm.test()
class sep_aes_mode_keysize_rand_test(sep_base_test):
    """Standalone AES ECB/CBC/CTR x 128/192/256 breadth (no_cpu, SW key)."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        # AES masking PRNG reseeds from crypto-EDN; bring the stack up (non-strict:
        # AES mode/key-size breadth proves AES, not the entropy golden) and drive the deterministic noise.
        await self.bring_up_entropy(strict=False, score_km=False)
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"

        self.aes = SepAes(self)
        seed = self.random_seed()
        self.rng = random.Random(seed)
        self.logger.info("AES mode/key-size breadth AES mode x key-size breadth: seed=%d", seed)
        await self.aes.trigger_prng_reseed()   # seed the masking PRNG from EDN

        walked = 0
        for mode in MODES:
            for key_bits in KEY_SIZES:
                await self._run_cell(mode, key_bits)
                walked += 1

        expected = len(MODES) * len(KEY_SIZES)
        assert walked == expected, f"walked {walked} cells != {expected}"
        await self.check_entropy_alerts_zero()
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells ({ECB,CBC,CTR} x "
            "{128,192,256}) in one invocation (seed=%d); key/IV/plaintext "
            "randomized per cell; entropy alerts clean", walked, seed)

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _run_cell(self, mode: str, key_bits: int) -> None:
        key = self._rand_words(key_bits // 32)
        pt = self._rand_words(4 * NUM_BLOCKS)
        iv = self._rand_words(4) if mode != "ecb" else None
        cfg = SepAesCfg(mode=mode, key_bits=key_bits, key_words=key,
                        pt_words=pt, iv_words=iv)
        cell = f"AES-{mode.upper()}-{key_bits}"

        # --- CHK-ENC: encrypt and value-check against the independent golden ---
        await self.aes.configure(mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(),
                                 operation=AES_OP_ENC)
        await self.aes.load_key_iv(key, iv)   # spec-ordered: idle between key + IV
        ct = await self.aes.run_blocks(pt)
        golden = aes_encrypt_words(**cfg.golden_kwargs())
        assert ct == golden, (
            f"{cell} ciphertext != golden:\n  ct    ={[hex(w) for w in ct]}\n"
            f"  golden={[hex(w) for w in golden]}")

        # CHK-NONVAC: not a passthrough, and a wrong key gives a different ct.
        assert ct != pt, f"{cell} ciphertext == plaintext (engine passthrough?)"
        wrong = aes_encrypt_words(mode=mode, key_words=[w ^ 0xFFFF_FFFF for w in key],
                                  pt_words=pt, iv_words=iv)
        assert ct != wrong, f"{cell} ct matches wrong-key golden (key not honored)"
        await self.aes.check_status_clean(cell + "-enc")   # CHK-STATUS

        # --- CHK-RT: recover the plaintext -----------------------------------
        if mode in ("ecb", "cbc"):
            await self.aes.configure(mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(),
                                     operation=AES_OP_DEC)
            await self.aes.load_key_iv(key, iv)      # CBC decrypt needs the original IV
            rt = await self.aes.run_blocks(ct)
        else:  # CTR is a stream cipher: re-encrypting the ciphertext yields the pt
            await self.aes.configure(mode=cfg.mode_ctrl(), key_len=cfg.keylen_ctrl(),
                                     operation=AES_OP_ENC)
            await self.aes.load_key_iv(key, iv)
            rt = await self.aes.run_blocks(ct)
        assert rt == pt, (
            f"{cell} round-trip != plaintext:\n  rt={[hex(w) for w in rt]}\n"
            f"  pt={[hex(w) for w in pt]}")
        await self.aes.check_status_clean(cell + "-rt")

        self.logger.info("CHK-CELL PASS %s: ct==golden, round-trip==pt, no alert, "
                         "non-vacuous (%d blocks)", cell, NUM_BLOCKS)
