# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-DSA-87 keyGen NIST KAT on the ABR aperture.

no_cpu host-AXI. Software-written seed path only (the key-CSR stub zeros
shares, so the key-vault seed path is not honest here). Public key is
compared word-for-word against the vendored NIST ACVP vector. Sensitivity:
flip one seed bit and the key must differ. PIC [34] stays low; [35] rises
on completion. ML-KEM, sign/verify, and the key-vault seed path are not
claimed.

RANDCFG: masking entropy and the flipped seed bit come from the run seed.
no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
import pyuvm

from sep_base_test import sep_base_test
from env.sep_abr_nist import NIST_KG_PK, NIST_KG_SEED
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_NAME0,
    ABR_NAME1,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    ABR_ENTROPY,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    IRQ_ABR_ERROR,
    IRQ_ABR_NOTIF,
    NAME0_EXP,
    NAME1_EXP,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
    SepAbrKeygenCfg,
)

# Status poll: 32-bit beat on an odd-word offset, with a cycle gap so a long
# keyGen does not spend the budget on back-to-back AXI. 20000 * 200 cycles is
# the backstop; a hang fails this wait rather than the sim timeout.
_POLL_ITERS = 20000
_POLL_GAP = 200


@pyuvm.test()
class sep_abr_mldsa_keygen_kat_test(sep_base_test):
    """ML-DSA-87 keyGen: NIST pk match, sensitivity flip, PIC [34]/[35]."""

    async def _irq(self, idx: int) -> int:
        await RisingEdge(cocotb.top.clk_i)
        return (self.rd(cocotb.top.sep_internal_interrupts_probe_o) >> idx) & 1

    async def _wait_status(self, abr: SepAbr, mask: int, expect: int, *, what: str) -> int:
        for _ in range(_POLL_ITERS):
            st = await abr.rd32(ABR_STATUS)
            if (st & mask) == expect:
                return st
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        raise AssertionError(
            f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x} "
            f"in {_POLL_ITERS} polls"
        )

    async def _keygen(self, abr: SepAbr, seed_words: list[int],
                      entropy: list[int], *, what: str) -> list[int]:
        await self._wait_status(abr, ST_READY, ST_READY, what=f"{what} READY")
        await abr.write_words(ABR_SEED, seed_words)
        await abr.write_words(ABR_ENTROPY, entropy)
        await abr.wr32(ABR_CTRL, CMD_KEYGEN)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"{what} VALID")
        assert (st & ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        return await abr.read_words(ABR_PUBKEY, PK_WORDS)

    async def run_scenario(self) -> None:
        cfg = SepAbrKeygenCfg(self.random_seed())
        self.logger.info("abr mldsa keygen: %s", cfg.summary())

        await self.bring_up_no_cpu()
        abr = SepAbr(self)

        name0 = await abr.rd32(ABR_NAME0)
        name1 = await abr.rd32(ABR_NAME1)
        assert name0 == NAME0_EXP and name1 == NAME1_EXP, (
            f"MLDSA NAME 0x{name0:08x}_0x{name1:08x}, "
            f"expected 0x{NAME0_EXP:08x}_0x{NAME1_EXP:08x} (MLDSA-87)"
        )
        self.logger.info(
            "CHK-NAME PASS: NAME0=0x%08x NAME1=0x%08x (MLDSA-87)", name0, name1)

        st0 = await abr.rd32(ABR_STATUS)
        assert (st0 & ST_READY) and not (st0 & ST_VALID) and not (st0 & ST_ERROR), (
            f"post-reset STATUS=0x{st0:08x}, expected READY, not VALID, not ERROR"
        )
        self.logger.info(
            "CHK-RESET-STATUS PASS: STATUS=0x%08x READY, not VALID, not ERROR", st0)

        await abr.enable_notif()
        assert await self._irq(IRQ_ABR_ERROR) == 0
        assert await self._irq(IRQ_ABR_NOTIF) == 0

        pk = await self._keygen(abr, list(NIST_KG_SEED), cfg.entropy, what="nist-keygen")
        mismatch = next((i for i, (g, e) in enumerate(zip(pk, NIST_KG_PK)) if g != e), None)
        assert mismatch is None, (
            f"NIST pk mismatch at word {mismatch}: "
            f"got=0x{pk[mismatch]:08x} exp=0x{NIST_KG_PK[mismatch]:08x}"
        )
        assert await self._irq(IRQ_ABR_ERROR) == 0, "[34] (abr error) high after keyGen"
        assert await self._irq(IRQ_ABR_NOTIF) == 1, "[35] (abr notif) low after keyGen"
        self.logger.info(
            "CHK-NIST-PK PASS: %d-word public key matches ACVP keyGen vector; "
            "CHK-STATUS-VALID PASS: VALID, ERROR=0; "
            "CHK-PIC-NOTIF PASS: [35]=1 [34]=0", PK_WORDS)

        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_READY, ST_READY, what="post-zeroize READY")

        flipped = cfg.flipped_seed(list(NIST_KG_SEED))
        pk2 = await self._keygen(abr, flipped, cfg.entropy, what="sensitivity-keygen")
        assert pk2 != pk, (
            "sensitivity keyGen returned the same pk as the NIST vector "
            f"(flip word {cfg.flip_word} bit {cfg.flip_bit} did not land)"
        )
        self.logger.info(
            "CHK-SENSITIVITY PASS: flipped seed word %d bit %d produced a "
            "different public key", cfg.flip_word, cfg.flip_bit)

        self.logger.info("abr mldsa keygen ALL CHECKS PASS")
