# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> ABR ML-DSA seed sideload: same PK as a direct software seed.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

Loads an 8-word palindromic seed over the mailbox (dest ABR ML-DSA seed),
pulls it through the KV seed-read control, and runs KEYGEN. The public key
must match a direct-seed KEYGEN of the same words. The palindrome absorbs
the KV dword reversal. Masking entropy is RANDCFG; the seed itself is
directed so the two KEYGENs stay comparable.
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
    ABR_KV_RD_SEED_READ_EN,
    ABR_MLDSA_KV_RD_SEED_CTRL,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    ENTROPY_WORDS,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
)
from seq_lib.sep_km_mailbox_seq import KM_DEST_ABR_MLDSA_SEED, KM_RC_SUCCESS, SepKmMailbox

# fw/tests/sep_abr_km_seed_test/sep_abr_km_seed_test.c
_ABR_SEED_PAL = [
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0xFEEDFACE,
    0xA5A5A5A5,
    0x13572468,
    0x0BADC0DE,
]

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

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        entropy = [rng.getrandbits(32) for _ in range(ENTROPY_WORDS)]
        if not any(w != 0 for w in entropy):
            entropy[0] = 0xA5A5A5A5
        self.logger.info(
            "km abr seed: seed=%s entropy[0]=0x%08x", self.random_seed(), entropy[0]
        )

        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        abr = SepAbr(self)
        self.km = SepKmMailbox(self)
        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        await self._wait_status(abr, ST_READY, ST_READY, what="direct READY")
        await abr.write_words(ABR_SEED, _ABR_SEED_PAL)
        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what="direct VALID")
        assert (st & ST_ERROR) == 0, f"direct KEYGEN VALID with ERROR (0x{st:08x})"
        pk_direct = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        assert any(w != 0 for w in pk_direct), "CHK-DIRECT FAIL: direct PK is all zero"
        self.logger.info(
            "CHK-DIRECT PASS: direct-seed PK[0..3]=0x%08x 0x%08x 0x%08x 0x%08x",
            pk_direct[0],
            pk_direct[1],
            pk_direct[2],
            pk_direct[3],
        )

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="post-zeroize READY")

        handle = await self.km.key_load(key_words=list(_ABR_SEED_PAL), dest=KM_DEST_ABR_MLDSA_SEED)
        rc, arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_ABR_MLDSA_SEED)
        assert rc == KM_RC_SUCCESS, f"CHK-XFER FAIL: CMD_KEY_TRANSFER dest=0x10 rc={rc}"
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == KM_DEST_ABR_MLDSA_SEED, (
            f"CHK-XFER FAIL: RETURN_ARG 0x{arg:08x} does not echo handle "
            f"0x{handle:02x} dest 0x10"
        )
        self.logger.info("CHK-XFER PASS: dest=0x10 (abr_mldsa_seed) rc=0 handle=0x%02x", handle)

        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.wr32(ABR_MLDSA_KV_RD_SEED_CTRL, ABR_KV_RD_SEED_READ_EN)
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what="km VALID")
        assert (st & ST_ERROR) == 0, f"KM KEYGEN VALID with ERROR (0x{st:08x})"
        pk_km = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        assert any(w != 0 for w in pk_km), "CHK-PK FAIL: KM-sideloaded PK is all zero"
        assert pk_km == pk_direct, (
            "CHK-PK FAIL: KM-sideloaded PK != direct-seed PK:\n"
            f"  direct[0..3]={[hex(w) for w in pk_direct[:4]]}\n"
            f"  km[0..3]    ={[hex(w) for w in pk_km[:4]]}"
        )
        self.logger.info(
            "CHK-PK PASS: KM-sideloaded PK equals the direct-seed PK (%d words)",
            PK_WORDS,
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        self.logger.info("entropy alerts clear after ABR sideload")
