# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> ABR ML-DSA-87 keyGen NIST KAT on the Key Manager path.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

The ACVP keyGen seed (``env/sep_abr_nist.py``, parsed from
``fw/tests/common/abr_nist_vectors.h``) is delivered only through the Key
Manager: CMD_KEY_LOAD + CMD_KEY_TRANSFER to dest ABR ML-DSA seed, then the KV
seed read. It is never written to the ABR seed registers, so a public key equal
to the ACVP public key can only come from the delivered seed. Key Manager word
i is register index MLDSA_SEED[i], and index 0 holds the first four bytes of
the FIPS 204 seed (doc/adams_bridge.adoc, abr-seed-word-order), so the seed
words go to the Key Manager in the same order sep_abr_mldsa_keygen_kat_test
writes them to the registers. The eight seed words are pairwise distinct, so a
dword reversal or any other word permutation in delivery fails the compare.

Checkers:
  CHK0        rom_main boots on real entropy and announces RESP_KM_READY
  CHK-XFER    CMD_KEY_TRANSFER of the ACVP seed to dest ABR ML-DSA seed returns
              success and echoes the handle and dest
  CHK-KV      the KV seed read completes: kv_mldsa_seed_rd_status VALID with
              ERROR == SUCCESS (kv_def.rdl encoding)
  CHK-KM-KAT  the KEYGEN public key equals the ACVP keyGen public key, all
              648 words

RANDCFG: masking entropy (SepAbrKeygenCfg). The seed is the ACVP vector.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_abr_nist import NIST_KG_PK, NIST_KG_SEED
from env.sep_spec_tables import kv_error_code, kv_status_field
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_KV_RD_SEED_READ_EN,
    ABR_MLDSA_KV_RD_SEED_CTRL,
    ABR_MLDSA_KV_RD_SEED_STATUS,
    ABR_PUBKEY,
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

KV_SUCCESS = kv_error_code("SUCCESS")

assert len(set(NIST_KG_SEED)) == len(NIST_KG_SEED), (
    "test construction error: the ACVP seed repeats a word, so a word permutation "
    "in delivery could leave it unchanged"
)
assert len(NIST_KG_PK) == PK_WORDS, "test construction error: ACVP public key size"

_POLL_ITERS = 20000
_POLL_GAP = 200
_KV_STATUS_POLLS = 2000


@pyuvm.test()
class sep_km_abr_mldsa_kat_test(sep_base_test):
    """ML-DSA-87 KEYGEN on a KM-delivered ACVP seed equals the ACVP public key."""

    required_evidence = ("CHK-XFER", "CHK-KV", "CHK-KM-KAT")

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

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="pre-KAT READY")

        handle = await self.km.key_load(key_words=list(NIST_KG_SEED), dest=KM_DEST_ABR_MLDSA_SEED)
        rc, arg = await self.km.key_transfer(handle=handle, dest=KM_DEST_ABR_MLDSA_SEED)
        assert rc == KM_RC_SUCCESS, f"CHK-XFER FAIL: CMD_KEY_TRANSFER dest=0x10 rc={rc}"
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == KM_DEST_ABR_MLDSA_SEED, (
            f"CHK-XFER FAIL: RETURN_ARG 0x{arg:08x} does not echo handle 0x{handle:02x} dest 0x10"
        )
        self.logger.info(
            "CHK-XFER PASS: ACVP seed to dest=0x10 (abr_mldsa_seed) rc=0 handle=0x%02x "
            "seed[0]=0x%08x seed[7]=0x%08x",
            handle,
            NIST_KG_SEED[0],
            NIST_KG_SEED[7],
        )

        await abr.wr32(ABR_MLDSA_KV_RD_SEED_CTRL, ABR_KV_RD_SEED_READ_EN)
        st = 0
        for _ in range(_KV_STATUS_POLLS):
            st = await abr.rd32(ABR_MLDSA_KV_RD_SEED_STATUS)
            if kv_status_field(st, "VALID") or kv_status_field(st, "ERROR") != KV_SUCCESS:
                break
            await ClockCycles(cocotb.top.clk_i, 20)
        err = kv_status_field(st, "ERROR")
        assert kv_status_field(st, "VALID") == 1 and err == KV_SUCCESS, (
            f"CHK-KV FAIL: KV seed read of the delivered ACVP seed did not complete "
            f"cleanly: status 0x{st:08x} ERROR={err} (SUCCESS={KV_SUCCESS})"
        )
        self.logger.info("CHK-KV PASS: KV seed read status 0x%08x (VALID, ERROR=SUCCESS)", st)

        await abr.write_words(ABR_ENTROPY, cfg.entropy)
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what="CHK-KM-KAT VALID")
        assert (st & ST_ERROR) == 0, f"CHK-KM-KAT FAIL: VALID with ERROR (0x{st:08x})"
        pk = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        assert len(pk) == PK_WORDS, f"CHK-KM-KAT FAIL: read {len(pk)} public-key words"
        bad = next((i for i, (g, e) in enumerate(zip(pk, NIST_KG_PK)) if g != e), None)
        assert bad is None, (
            f"CHK-KM-KAT FAIL: the public key from the KM-delivered ACVP seed differs from "
            f"the ACVP public key at word {bad} of {PK_WORDS}: got=0x{pk[bad]:08x} "
            f"exp=0x{NIST_KG_PK[bad]:08x}"
        )
        self.logger.info(
            "CHK-KM-KAT PASS: the %d-word public key from the KM-delivered ACVP seed equals "
            "the ACVP keyGen public key (pk[0]=0x%08x pk[%d]=0x%08x)",
            PK_WORDS,
            pk[0],
            PK_WORDS - 1,
            pk[PK_WORDS - 1],
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
