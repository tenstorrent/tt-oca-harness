# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each HMAC SHA-2 variant and legal key length, keyed and plain, matches an independent golden.

RAND-REP. The test drives the OpenTitan HMAC engine directly over the CPU-LSU AXI master (no_cpu, no
firmware) across the full standalone SW-key matrix that the KM->HMAC
sideload KAT (`sep_km_hmac_sideload_kat_test`, SHA-256 keyed via keymgr_key_i)
does not reach:

    {SHA-256, SHA-384, SHA-512} x {keyed HMAC, plain SHA} x legal key-length.

The independent stdlib golden (env/sep_hmac_golden.py, HMAC-SHA256/384/512 RFC 4231 +
plain SHA FIPS-180, self-tested) is the reference. Distinct from
`sep_km_hmac_sideload_kat_test` (SHA-256 via SIDELOAD) and the CPU
crypto smoke (SHA-256): HMAC SHA-variant breadth is standalone SW-key across variants.

One SepHmacCfg object drives both the DUT programming (CFG, key) and the golden.
Every legal {sha_bits x mode x key_bits} cell is walked on every seed, so a single
seed never skips a required cell. The seed sets only the key and the message
content and length. The SHA-256 x Key_1024 keyed cell is illegal -- hmac.adoc states the key length
cannot exceed the block size, 512-bit for SHA-2 256 -- and is excluded by the
block-size rule the sequence derives, not by a hand-listed pair.

Checkers:
  CHK-CONV     SW-key register convention pinned on SHA-256 keyed-256 from the IP
               register spec (vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson,
               KEY multireg), asserted against the engine -- not selected by asking which
               candidate convention the engine agrees with
  CHK-CELL     per cell: engine DIGEST == independent golden (8/12/16 words)
  CHK-RW1C     per cell: INTR_STATE.hmac_done reads 1 right before its W1C and 0
               after it (hmac.adoc INTR_STATE: hmac_done RW1C)
  CHK-ERR      per cell: ERR_CODE == 0 and INTR_STATE.hmac_err == 0
  CTRL-HMAC-KEY-FILL per keyed cell: every KEY register above key_length is
               written with a seeded non-zero word before the key, so a key_length
               decoded too long changes the digest and fails CHK-CELL (hmac.hjson
               KEY: key_length determines which registers are relevant)
  CHK-RAND-REP every legal cell produced its own golden-matching digest, and all
               digests are distinct (seed logged)
"""

from __future__ import annotations

import pyuvm
from env.sep_hmac_golden import hmac_or_sha_words
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_hmac_seq import (
    HMAC_CMD,
    HMAC_CMD_HASH_PROCESS,
    HMAC_CMD_HASH_START,
    HMAC_DIGEST,
    HMAC_DIGEST_SIZE,
    HMAC_DIGEST_WORDS,
    HMAC_ILLEGAL_KEYED,
    HMAC_INTR_DONE,
    HMAC_INTR_STATE,
    HMAC_KEY,
    HMAC_KEY_LENGTH,
    HMAC_MSG_FIFO,
    SepHmac,
    SepHmacCfg,
)

# Derived, not hand-kept: the full digest-size x key-length product minus the
# combinations the register specification blocks. HMAC_ILLEGAL_KEYED in the
# sequence derives those from hmac.adoc's block-size rule and is the single
# source of truth for legality, so a change there moves both the stimulus and
# this matrix together.
KEYED_MATRIX = {
    sha_bits: [k for k in HMAC_KEY_LENGTH if (sha_bits, k) not in HMAC_ILLEGAL_KEYED]
    for sha_bits in HMAC_DIGEST_SIZE
}
EXCLUDED_KEYED = tuple(sorted(HMAC_ILLEGAL_KEYED))
SHA_VARIANTS = list(HMAC_DIGEST_SIZE)

# Fixed known key/msg for the one-time SW-key convention resolution (8 distinct
# words so word-order reversal yields a distinct key).
_CONV_KEY = [
    0xDEADBEEF,
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x01234567,
    0x89ABCDEF,
    0xFEDCBA98,
]
_CONV_MSG = [0x00010203, 0x04050607, 0x08090A0B, 0x0C0D0E0F]


class _SepHmacRw1c(SepHmac):
    """SepHmac with a hash run that returns the INTR_STATE reads taken right
    before and right after the hmac_done write-one-to-clear."""

    async def run_mac_rw1c(
        self, msg_words: list[int], *, sha_bits: int
    ) -> tuple[list[int], int, int]:
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_START)
        for word in msg_words:
            await self._wait_fifo_space()
            await self._wr(HMAC_MSG_FIFO, word & 0xFFFF_FFFF)
        await self._wr(HMAC_CMD, HMAC_CMD_HASH_PROCESS)
        await self._wait_done()
        digest = [await self._rd(HMAC_DIGEST[i]) for i in range(HMAC_DIGEST_WORDS[sha_bits])]
        pre = await self._rd(HMAC_INTR_STATE)
        await self._wr(HMAC_INTR_STATE, HMAC_INTR_DONE)
        post = await self._rd(HMAC_INTR_STATE)
        return digest, pre, post


@pyuvm.test()
class sep_hmac_sha_variant_rand_test(sep_base_test):
    """HMAC SHA-256/384/512, keyed and plain, with a SW key each match the golden."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.hmac = _SepHmacRw1c(self)
        seed = self.random_seed()
        self.rng = SepSeededRng(seed)
        self.logger.info("HMAC SHA-variant breadth: seed=%d", seed)

        # CHK-CONV: pin the SW-key register byte convention once (bring-up).
        conv = await self._check_key_convention()

        # Collect each cell's DUT result so the matrix claim rests on observed
        # output, not on the loop's own trip count. Distinct results additionally
        # show the cells programmed different configurations.
        results: dict[str, tuple[int, ...]] = {}
        for sha_bits in SHA_VARIANTS:
            for key_bits in KEYED_MATRIX[sha_bits]:
                results[f"hmac{sha_bits}-k{key_bits}"] = await self._run_cell(
                    sha_bits, True, key_bits, conv
                )
            results[f"sha{sha_bits}"] = await self._run_cell(sha_bits, False, None, conv)

        walked = len(results)
        expected = sum(len(v) for v in KEYED_MATRIX.values()) + len(SHA_VARIANTS)
        # Construction guard, not a DUT contract: this compares the walk against
        # the cell list that drove it, so only a table or keying mistake in this
        # file can trip it. The DUT evidence is the per-cell golden compare.
        assert walked == expected, f"walked {walked} cells != {expected} required"
        assert len(set(results.values())) == expected, (
            "HMAC cells produced duplicate digests, so they did not all run distinct "
            "configurations: " + ", ".join(f"{k}={results[k][0]:#010x}" for k in sorted(results))
        )
        for sha_bits, key_bits in EXCLUDED_KEYED:
            self.logger.info(
                "INFO-SKIP-ILLEGAL-KEYED: SHA-%d with a %d-bit key exceeds the SHA-2 "
                "block size, which hmac.adoc says blocks the start and signals an "
                "error, so it is not a keyed cell. "
                "Declared, not driven: no negative cell provokes ERR_CODE here",
                sha_bits,
                key_bits,
            )
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells "
            "({SHA256,384,512} x keyed[all legal key-len] + plain-SHA) in one "
            "invocation (seed=%d); key+message randomized per cell",
            walked,
            seed,
        )

    def _rand_words(self, n: int) -> list[int]:
        return [self.rng.getrandbits(32) for _ in range(n)]

    # Register convention for the software key path, taken from the register
    # specification rather than from the RTL or from the DUT.
    #
    # vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson, KEY multireg:
    #     Order of the secret key is:  key[1023:0] = {KEY0, KEY1, KEY2, ... , KEY31};
    # so KEY_0 is the most-significant word, and hmac_core consumes
    # secret_key_i[1023:768] for a 256-bit key. Writing KEY_0..KEY_7 in order therefore
    # lays the key down MSB-first and needs no word reversal.
    #
    # The RTL agrees (hmac.sv assigns the key registers in reverse index order), but
    # the specification is the citation: an expectation transcribed from the thing it
    # measures cannot disagree with it.
    #
    # Do not confuse this with the SIDELOAD path, where
    # vendor/lowRISC/opentitan/upstream/hw/ip/hmac/rtl/hmac.sv packs
    # {key[0] ^ key[1], 768'b0} -- a different mechanism with a different convention.
    # sep_hmac_golden's module docstring describes that one.
    _SW_KEY_CONV = dict(key_word_rev=False, key_be=True, msg_be=False, digest_swap=False)

    async def _check_key_convention(self) -> dict:
        """Verify the engine honours the SPECIFIED SW-key convention
        (vendor/lowRISC/opentitan/upstream/hw/ip/hmac/data/hmac.hjson, KEY multireg).

        Asserts against the pinned convention. On mismatch, reports whether the
        reversed convention would have matched, because that distinguishes a key
        word-order regression from a general digest fault.
        """
        cfg = SepHmacCfg(
            sha_bits=256,
            hmac_en=True,
            key_bits=256,
            key_words=list(_CONV_KEY),
            msg_words=list(_CONV_MSG),
        )
        await self.hmac.configure(cfg.cfg_word())
        await self.hmac.write_key(_CONV_KEY)
        digest = await self.hmac.run_mac(list(_CONV_MSG), sha_bits=256)

        expected = hmac_or_sha_words(
            hmac_en=True,
            sha_bits=256,
            key_words=list(_CONV_KEY),
            msg_words=list(_CONV_MSG),
            **self._SW_KEY_CONV,
        )
        if digest != expected:
            reversed_conv = dict(self._SW_KEY_CONV, key_word_rev=True)
            also = hmac_or_sha_words(
                hmac_en=True,
                sha_bits=256,
                key_words=list(_CONV_KEY),
                msg_words=list(_CONV_MSG),
                **reversed_conv,
            )
            hint = (
                " -- the REVERSED word order matches, so this is a key word-order "
                "regression in the SW KEY CSR path (hmac.sv update_secret_key)"
                if digest == also
                else " -- neither word order matches, so this is not a word-order issue"
            )
            raise AssertionError(
                f"CHK-CONV: engine digest does not honour the specified SW-key convention "
                f"{self._SW_KEY_CONV}{hint}\n"
                f"  engine  ={[hex(w) for w in digest]}\n"
                f"  expected={[hex(w) for w in expected]}"
            )
        self.logger.info(
            "CHK-CONV PASS: engine honours the specified SW-key convention "
            "(key_word_rev=False, KEY_0 is the most-significant word)"
        )
        return dict(self._SW_KEY_CONV)

    async def _fill_upper_key(self, key_bits: int, mode: str) -> int:
        """Write a seeded non-zero word to every KEY register above key_bits.

        The golden zero-pads the key to the block size, so a zero upper KEY word
        cannot tell the programmed key_length from a longer one.
        """
        first = key_bits // 32
        for i in range(first, len(HMAC_KEY)):
            await self.hmac._wr(HMAC_KEY[i], self.rng.randrange(1, 1 << 32))
        filled = len(HMAC_KEY) - first
        self.logger.info(
            "CTRL-HMAC-KEY-FILL %s: %d seeded non-zero words in KEY_%d..KEY_%d",
            mode,
            filled,
            first,
            len(HMAC_KEY) - 1,
        )
        return filled

    async def _run_cell(
        self, sha_bits: int, hmac_en: bool, key_bits: int | None, conv: dict
    ) -> tuple[int, ...]:
        msg = self._rand_words(self.rng.randrange(1, 17))
        key = self._rand_words(key_bits // 32) if hmac_en else []
        cfg = SepHmacCfg(
            sha_bits=sha_bits,
            hmac_en=hmac_en,
            key_bits=key_bits,
            key_words=key,
            msg_words=msg,
            **conv,
        )
        mode = f"HMAC-SHA{sha_bits}/Key_{key_bits}" if hmac_en else f"SHA{sha_bits}"

        await self.hmac.configure(cfg.cfg_word())
        filled = 0
        if hmac_en:
            filled = await self._fill_upper_key(key_bits, mode)
            await self.hmac.write_key(key)
        digest, pre, post = await self.hmac.run_mac_rw1c(msg, sha_bits=sha_bits)
        pre_done = int(bool(pre & HMAC_INTR_DONE))
        post_done = int(bool(post & HMAC_INTR_DONE))
        if pre_done != 1 or post_done != 0:
            raise AssertionError(
                f"CHK-RW1C FAIL {mode}: hmac_done before W1C={pre_done} expected 1 "
                f"(0x{pre:08x}), after W1C={post_done} expected 0 (0x{post:08x})"
            )
        self.logger.info(
            "CHK-RW1C PASS %s: hmac_done before W1C=1 (0x%08x), after W1C=0 (0x%08x)",
            mode,
            pre,
            post,
        )

        golden = hmac_or_sha_words(**cfg.golden_kwargs())
        assert digest == golden, (
            f"{mode} DIGEST != golden:\n  digest={[hex(w) for w in digest]}\n"
            f"  golden={[hex(w) for w in golden]}"
        )

        await self.hmac.check_status_clean(mode)
        self.logger.info("CHK-ERR PASS %s: ERR_CODE == 0 and INTR_STATE.hmac_err == 0", mode)
        self.logger.info(
            "CHK-CELL PASS %s: DIGEST==golden, RW1C done, ERR clean, non-vacuous "
            "(msg=%d words, upper KEY fill=%d)",
            mode,
            len(msg),
            filled,
        )
        return tuple(digest)
