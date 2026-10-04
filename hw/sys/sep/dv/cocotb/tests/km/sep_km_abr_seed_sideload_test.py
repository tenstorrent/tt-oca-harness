# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> ABR ML-DSA seed sideload: same PK as a direct software seed.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

Loads an 8-word seed over the mailbox (dest ABR ML-DSA seed), pulls it
through the KV seed-read control, and runs KEYGEN. The public key must match
a direct-seed KEYGEN of the same words. Key Manager word i and register
index MLDSA_SEED[i] carry the same dword (doc/adams_bridge.adoc,
abr-seed-word-order), and the eight seed words are pairwise distinct, so a
delivery that permutes the words -- a dword reversal included -- changes the
seed and fails the compare. Masking entropy is RANDCFG; the seed itself is
directed so the two KEYGENs stay comparable.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_KV_RD_SEED_READ_EN,
    ABR_MLDSA_KV_RD_SEED_CTRL,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
    SepAbrKeygenCfg,
)
from seq_lib.sep_km_mailbox_seq import KM_DEST_ABR_MLDSA_SEED, KM_RC_SUCCESS, SepKmMailbox

# Two directed seeds. Each has eight pairwise-distinct words, so any word
# permutation in delivery yields a different seed and a different public key.
_ABR_SEED = [
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0x2468ACE0,
    0x5A5A0F0F,
    0x97531ECA,
    0x600DF00D,
]

# A second, distinct seed for the KM sideload leg. The sideload must not reuse
# _ABR_SEED: the direct keygen above already wrote that value into
# MLDSA_SEED, so a ZEROIZE that failed to clear the register would produce the
# same public key and CHK-PK could not tell a working sideload from a stale
# seed.
_ABR_SEED_ALT = [
    0x1234ABCD,
    0x0F0F0F0F,
    0xC0FFEE00,
    0x5EED5EED,
    0x7E57CA5E,
    0x31415926,
    0x4B1D2C3E,
    0x8BADF00D,
]

for _seed in (_ABR_SEED, _ABR_SEED_ALT):
    assert len(set(_seed)) == len(_seed), "test construction error: repeated seed word"

_POLL_ITERS = 20000
_POLL_GAP = 200


@pyuvm.test()
class sep_km_abr_seed_sideload_test(sep_base_test):
    """ABR KEYGEN from a KM-sideloaded seed equals the direct-seed KEYGEN."""

    async def _wait_status(self, abr: SepAbr, mask: int, expect: int, *, what: str) -> int:
        for _ in range(_POLL_ITERS):
            st = await abr.rd32(ABR_STATUS)
            if (st & mask) == expect:
                return st
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        raise AssertionError(
            f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x} in {_POLL_ITERS} polls"
        )

    async def _keygen(
        self, abr: SepAbr, seed_words: list[int] | None, entropy: list[int], *, what: str
    ) -> list[int]:
        if seed_words is not None:
            await abr.write_words(ABR_SEED, seed_words)
        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"{what} VALID")
        assert (st & ST_ERROR) == 0, f"{what} VALID with ERROR (0x{st:08x})"
        pk = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        assert any(w != 0 for w in pk), f"{what} FAIL: PK is all zero"
        return pk

    async def run_scenario(self) -> None:
        cfg = SepAbrKeygenCfg(self.random_seed())
        self.logger.info("RANDCFG: %s", cfg.summary())

        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        abr = SepAbr(self)
        self.km = SepKmMailbox(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        await self._wait_status(abr, ST_READY, ST_READY, what="direct READY")
        pk_direct = await self._keygen(abr, _ABR_SEED, cfg.entropy, what="CHK-DIRECT")
        self.logger.info(
            "CHK-DIRECT PASS: direct-seed PK[0..3]=0x%08x 0x%08x 0x%08x 0x%08x",
            pk_direct[0],
            pk_direct[1],
            pk_direct[2],
            pk_direct[3],
        )

        # ABR_ENTROPY is SCA masking: write-only, and the RDL requires no change
        # on the outputs. Invert the vector and the public key must stay the same.
        contrast = [(~w) & 0xFFFF_FFFF for w in cfg.entropy]
        assert contrast != cfg.entropy, "CHK-RANDCFG FAIL: invert collapsed to cfg.entropy"
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="contrast READY")
        pk_contrast = await self._keygen(abr, _ABR_SEED, contrast, what="CHK-RANDCFG")
        assert pk_contrast == pk_direct, (
            "CHK-RANDCFG FAIL: inverted masking entropy changed the public key"
        )
        self.logger.info("CHK-RANDCFG PASS: inverted masking entropy left the public key unchanged")

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="post-zeroize READY")

        # Reference for the sideload leg: the same distinct seed, driven the
        # direct way. CHK-PK below compares against this, not against pk_direct,
        # so the compare fails if the sideload delivered the earlier seed.
        pk_alt = await self._keygen(abr, _ABR_SEED_ALT, cfg.entropy, what="CHK-PK-REF")
        assert pk_alt != pk_direct, (
            "CHK-PK-REF FAIL: the two seeds produce the same public key, so the "
            "sideload compare below could not distinguish them"
        )
        self.logger.info("CHK-PK-REF PASS: the alternate seed gives a distinct public key")

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="post-zeroize READY (alt)")

        pk_cleared = await self._keygen(abr, None, cfg.entropy, what="CHK-CLEAR")
        assert pk_cleared != pk_alt, (
            "CHK-CLEAR FAIL: a keygen with no software seed and no KV "
            "read-enable reproduced the alternate public key, so ZEROIZE "
            "left the seed register live"
        )
        self.logger.info(
            "CHK-CLEAR PASS: post-zeroize keygen without a seed differs from the reference PK"
        )

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="post-clear READY")

        handle = await self.km.key_load(key_words=list(_ABR_SEED_ALT), dest=KM_DEST_ABR_MLDSA_SEED)
        rc, arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_ABR_MLDSA_SEED)
        assert rc == KM_RC_SUCCESS, f"CHK-XFER FAIL: CMD_KEY_TRANSFER dest=0x10 rc={rc}"
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == KM_DEST_ABR_MLDSA_SEED, (
            f"CHK-XFER FAIL: RETURN_ARG 0x{arg:08x} does not echo handle 0x{handle:02x} dest 0x10"
        )
        self.logger.info("CHK-XFER PASS: dest=0x10 (abr_mldsa_seed) rc=0 handle=0x%02x", handle)

        await abr.wr32(ABR_MLDSA_KV_RD_SEED_CTRL, ABR_KV_RD_SEED_READ_EN)
        pk_km = await self._keygen(abr, None, cfg.entropy, what="CHK-PK")
        assert pk_km != pk_direct, (
            "CHK-PK FAIL: the sideload produced the FIRST seed's public key, so "
            "the seed register still held the earlier value -- a stale seed, not "
            "a delivered one"
        )
        assert pk_km == pk_alt, (
            "CHK-PK FAIL: KM-sideloaded PK != direct alternate-seed PK, so Key "
            "Manager word i did not reach MLDSA_SEED[i] (a lost, stale or "
            "reordered seed word):\n"
            f"  alt[0..3]={[hex(w) for w in pk_alt[:4]]}\n"
            f"  km[0..3] ={[hex(w) for w in pk_km[:4]]}"
        )
        self.logger.info(
            "CHK-PK PASS: KM-sideloaded PK equals the direct-seed PK of the same "
            "word order (%d words, pk[0]=0x%08x); seed[0]=0x%08x seed[7]=0x%08x",
            PK_WORDS,
            pk_km[0],
            _ABR_SEED_ALT[0],
            _ABR_SEED_ALT[7],
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
