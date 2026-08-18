# SPDX-License-Identifier: Apache-2.0
"""Standalone HMAC SHA-variant breadth, RAND-REP (HMAC SHA-variant breadth).

Drives the OpenTitan HMAC engine directly over the CPU-LSU AXI master (no_cpu, no
firmware) across the full standalone SW-key matrix that the Phase-1 KM->HMAC
sideload KAT (#12, SHA-256 keyed via keymgr_key_i) does not reach:

    {SHA-256, SHA-384, SHA-512} x {keyed HMAC, plain SHA} x legal key-length.

reference parity: this is a GAP (basic) rep -- the reference SEP tb has no SHA-384/512 HMAC
or key-length coverage (uvm_tests/hmac + fw hmac cover SHA-256 only). So the
independent stdlib golden (env/sep_hmac_golden.py, HMAC-SHA256/384/512 RFC 4231 +
plain SHA FIPS-180 self-tested) IS the reference and this rep is STRONGER than the
directed reference suite set it merges. DISTINCT from #12 (SHA-256 via SIDELOAD) and the CPU
crypto smoke (SHA-256): HMAC SHA-variant breadth is standalone SW-key across variants.

RAND-REP contract: a SepHmacCfg config object is the single source
of truth for BOTH the DUT programming (CFG + key) AND the golden. The required
discrete cells are WALKED DETERMINISTICALLY in one invocation (every legal
{sha_bits x mode x key_bits} cell), so a single seed never skips a required cell;
the seed only randomizes the legal continuous knobs (key + message content/
length). The SHA-256 x Key_1024 keyed cell is illegal (hmac.sv:819) and excluded.

Checkers:
  CHK-CONV     SW-key byte convention pinned on SHA-256 keyed-256 (exactly one of
               the candidate register conventions reproduces the engine digest)
  CHK-CELL     per cell: engine DIGEST == independent golden (8/12/16 words)
  CHK-RW1C     per cell: INTR_STATE.hmac_done W1C-clears to 0 (in run_mac)
  CHK-ERR      per cell: ERR_CODE == 0 and INTR_STATE.hmac_err == 0
  CHK-NONVAC   per cell: digest is non-zero, and keyed digest != plain-SHA digest
               of the same message (proves the key was actually consumed)
  CHK-RAND-REP all required discrete cells walked in one invocation (seed logged)
"""

from __future__ import annotations

import random

import pyuvm

from sep_base_test import sep_base_test
from env.sep_hmac_golden import hmac_or_sha_words
from seq_lib.sep_hmac_seq import SepHmac, SepHmacCfg

# Legal keyed cells: sha_bits -> allowed key_bits. SHA-256 excludes Key_1024
# (hmac.sv:819 invalid_config); SHA-384/512 support all five key lengths.
KEYED_MATRIX = {
    256: [128, 256, 384, 512],
    384: [128, 256, 384, 512, 1024],
    512: [128, 256, 384, 512, 1024],
}
SHA_VARIANTS = [256, 384, 512]

# Fixed known key/msg for the one-time SW-key convention resolution (8 distinct
# words so word-order reversal yields a distinct key).
_CONV_KEY = [0xDEADBEEF, 0x00112233, 0x44556677, 0x8899AABB,
             0xCCDDEEFF, 0x01234567, 0x89ABCDEF, 0xFEDCBA98]
_CONV_MSG = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]


@pyuvm.test()
class sep_hmac_sha_variant_rand_test(sep_base_test):
    """Standalone HMAC SHA-256/384/512 keyed+plain breadth (no_cpu, SW key)."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.hmac = SepHmac(self)
        seed = self.random_seed()
        self.rng = random.Random(seed)
        self.logger.info("HMAC SHA-variant breadth HMAC SHA-variant breadth: seed=%d", seed)

        # CHK-CONV: pin the SW-key register byte convention once (bring-up).
        conv = await self._resolve_key_convention()

        walked = 0
        for sha_bits in SHA_VARIANTS:
            for key_bits in KEYED_MATRIX[sha_bits]:
                await self._run_cell(sha_bits, True, key_bits, conv)
                walked += 1
            await self._run_cell(sha_bits, False, None, conv)
            walked += 1

        expected = sum(len(v) for v in KEYED_MATRIX.values()) + len(SHA_VARIANTS)
        assert walked == expected, f"walked {walked} cells != {expected} required"
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells "
            "({SHA256,384,512} x keyed[all legal key-len] + plain-SHA) in one "
            "invocation (seed=%d); key+message randomized per cell", walked, seed)

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    async def _resolve_key_convention(self) -> dict:
        """Run SHA-256 keyed-256 with a known key/msg and find which register byte
        convention reproduces the engine digest. Exactly one candidate must match
        (a broken engine matches neither -> FAIL), locking a non-value-agnostic
        convention for every subsequent cell."""
        cfg = SepHmacCfg(sha_bits=256, hmac_en=True, key_bits=256,
                         key_words=list(_CONV_KEY), msg_words=list(_CONV_MSG))
        await self.hmac.configure(cfg.cfg_word())
        await self.hmac.write_key(_CONV_KEY)
        digest = await self.hmac.run_mac(list(_CONV_MSG), sha_bits=256)

        candidates = [
            dict(key_word_rev=False, key_be=True, msg_be=False, digest_swap=False),
            dict(key_word_rev=True, key_be=True, msg_be=False, digest_swap=False),
        ]
        matches = [c for c in candidates
                   if hmac_or_sha_words(hmac_en=True, sha_bits=256,
                                        key_words=list(_CONV_KEY),
                                        msg_words=list(_CONV_MSG), **c) == digest]
        assert len(matches) == 1, (
            f"SW-key convention resolve found {len(matches)} matches (need exactly "
            f"1); engine digest={[hex(w) for w in digest]}")
        conv = matches[0]
        self.logger.info(
            "CHK-CONV PASS: SW-key convention pinned key_word_rev=%s key_be=%s "
            "msg_be=%s digest_swap=%s", conv["key_word_rev"], conv["key_be"],
            conv["msg_be"], conv["digest_swap"])
        return conv

    async def _run_cell(self, sha_bits: int, hmac_en: bool,
                        key_bits: int | None, conv: dict) -> None:
        msg = self._rand_words(self.rng.randint(1, 16))
        key = self._rand_words(key_bits // 32) if hmac_en else []
        cfg = SepHmacCfg(sha_bits=sha_bits, hmac_en=hmac_en, key_bits=key_bits,
                         key_words=key, msg_words=msg, **conv)
        mode = f"HMAC-SHA{sha_bits}/Key_{key_bits}" if hmac_en else f"SHA{sha_bits}"

        await self.hmac.configure(cfg.cfg_word())
        if hmac_en:
            await self.hmac.write_key(key)
        digest = await self.hmac.run_mac(msg, sha_bits=sha_bits)  # CHK-RW1C inside

        golden = hmac_or_sha_words(**cfg.golden_kwargs())
        assert digest == golden, (
            f"{mode} DIGEST != golden:\n  digest={[hex(w) for w in digest]}\n"
            f"  golden={[hex(w) for w in golden]}")

        # CHK-NONVAC: non-trivial digest, and (keyed) key actually consumed.
        assert any(digest), f"{mode} digest is all-zero (vacuous)"
        if hmac_en:
            plain = hmac_or_sha_words(hmac_en=False, sha_bits=sha_bits, msg_words=msg,
                                      msg_be=conv["msg_be"],
                                      digest_swap=conv["digest_swap"])
            assert digest != plain, f"{mode} keyed digest == plain-SHA (key ignored)"

        await self.hmac.check_status_clean(mode)  # CHK-ERR
        self.logger.info("CHK-CELL PASS %s: DIGEST==golden, RW1C done, ERR clean, "
                         "non-vacuous (msg=%d words)", mode, len(msg))
