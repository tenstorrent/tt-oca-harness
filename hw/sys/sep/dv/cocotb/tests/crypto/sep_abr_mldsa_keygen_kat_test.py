# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-DSA-87 keyGen NIST KAT on the ABR aperture.

no_cpu host-AXI. Software-written seed path only. Public key is
compared word-for-word against the vendored NIST ACVP vector. Sensitivity:
flip one seed bit and the key must differ. PIC [34] is proven live via
error_intr_trig (0->1, W1C -> 0) before the KAT, then stays low at
completion; [35] rises on completion and is W1C-cleared. ZEROIZE must
drop VALID, and the pubkey window must then read zero. ML-KEM,
sign/verify, and the key-vault seed path are not claimed, and neither is
the ABR_ZEROIZE memory walk itself -- see CHK-ZEROIZE below.

RANDCFG: masking entropy and the flipped seed bit come from the run seed.
no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_abr_nist import NIST_KG_PK, NIST_KG_SEED
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_NAME0,
    ABR_NAME1,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    ABR_VERSION0,
    ABR_VERSION1,
    CMD_KEYGEN,
    CTRL_ZEROIZE,
    IRQ_ABR_ERROR,
    IRQ_ABR_NOTIF,
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
        # Only bit ``idx`` must be known: it is the bit the must-be-0 and
        # must-be-1 legs compare, and an X there raises instead of reading 0.
        return self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, 1 << idx) >> idx

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
        self, abr: SepAbr, seed_words: list[int], entropy: list[int], *, what: str
    ) -> list[int]:
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

        # Logged for the record, not graded: abr_reg.rdl declares NAME and
        # VERSION sw=r with no reset, and no SEP document gives their values.
        name0 = await abr.rd32(ABR_NAME0)
        name1 = await abr.rd32(ABR_NAME1)
        ver0 = await abr.rd32(ABR_VERSION0)
        ver1 = await abr.rd32(ABR_VERSION1)
        self.logger.info(
            "ABR ML-DSA identity words (information only): NAME0=0x%08x NAME1=0x%08x "
            "VERSION0=0x%08x VERSION1=0x%08x",
            name0,
            name1,
            ver0,
            ver1,
        )

        st0 = await abr.rd32(ABR_STATUS)
        assert (st0 & ST_READY) and not (st0 & ST_VALID) and not (st0 & ST_ERROR), (
            f"post-reset STATUS=0x{st0:08x}, expected READY, not VALID, not ERROR"
        )
        self.logger.info("CHK-RESET-STATUS PASS: STATUS=0x%08x READY, not VALID, not ERROR", st0)

        await abr.enable_notif()
        assert await self._irq(IRQ_ABR_ERROR) == 0
        assert await self._irq(IRQ_ABR_NOTIF) == 0

        # Positive control for [34]: a stuck-low probe would pass the post-KAT
        # "[34]=0" check. error_intr_trig is the IP INTR_TEST equivalent.
        await abr.trigger_error()
        saw_err = False
        for _ in range(64):
            if await self._irq(IRQ_ABR_ERROR) == 1:
                saw_err = True
                break
        assert saw_err, "[34] stayed low after error_intr_trig (probe stuck-low / enable missed)"
        err_st = await abr.error_state()
        assert err_st & 1, f"error_internal_sts=0x{err_st:x} after trigger"
        err_st = await abr.w1c_error()
        assert (err_st & 1) == 0, f"error_internal_sts=0x{err_st:x} after W1C"
        assert await self._irq(IRQ_ABR_ERROR) == 0, "[34] still high after error_internal_sts W1C"
        self.logger.info("CHK-PIC-ERROR PASS: [34] 0->1 via error_intr_trig, W1C readback 0")

        pk = await self._keygen(abr, list(NIST_KG_SEED), cfg.entropy, what="nist-keygen")
        mismatch = next((i for i, (g, e) in enumerate(zip(pk, NIST_KG_PK)) if g != e), None)
        assert mismatch is None, (
            f"NIST pk mismatch at word {mismatch}: "
            f"got=0x{pk[mismatch]:08x} exp=0x{NIST_KG_PK[mismatch]:08x}"
        )
        assert await self._irq(IRQ_ABR_ERROR) == 0, "[34] (abr error) high after keyGen"
        assert await self._irq(IRQ_ABR_NOTIF) == 1, "[35] (abr notif) low after keyGen"
        self.logger.info(
            "CHK-NIST-PK PASS: %d-word public key matches ACVP keyGen vector", PK_WORDS
        )
        self.logger.info("CHK-STATUS-VALID PASS: VALID, ERROR=0")
        self.logger.info("CHK-PIC-NOTIF PASS: [35]=1 [34]=0")

        notif_st = await abr.notif_state()
        assert notif_st & 1, f"notif_internal_sts=0x{notif_st:x} after keyGen"
        notif_st = await abr.w1c_notif()
        assert (notif_st & 1) == 0, f"notif_internal_sts=0x{notif_st:x} after W1C"
        assert await self._irq(IRQ_ABR_NOTIF) == 0, "[35] still high after notif_internal_sts W1C"
        self.logger.info("CHK-PIC-NOTIF-W1C PASS: [35] 1->0 via notif_internal_sts W1C")

        # MLDSA_STATUS.READY is driven by abr_ready = (abr_prog_cntr ==
        # ABR_RESET) (abr_ctrl.sv), which is LOW through the ABR_ZEROIZE walk --
        # abr_idle is a different signal and is not in STATUS -- so a
        # READY-high wait here would hang rather than pass vacuously. VALID
        # must fall, and the pubkey window must then read zero.
        #
        # Scope of the pubkey half: the read port is gated on mldsa_valid_reg
        # (abr_ctrl.sv api_pubkey_re), so once VALID is 0 the window returns 0
        # whether or not the memory walk ran. This proves the window is no
        # longer readable, NOT that the RAM was wiped. Proving the wipe needs a
        # probe on the pubkey RAM or on zeroize_mem_done; it is not claimed.
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        st_z = await self._wait_status(abr, ST_VALID, 0, what="post-zeroize VALID clear")
        assert (st_z & ST_ERROR) == 0, f"post-zeroize STATUS=0x{st_z:08x}, expected VALID=0 ERROR=0"
        # Read the whole window, not a prefix: ZEROIZE must clear all of it, and
        # the KAT already pays for a full-window read.
        pk_z = await abr.read_words(ABR_PUBKEY, PK_WORDS)
        live = [(i, w) for i, w in enumerate(pk_z) if w != 0]
        assert not live, (
            f"post-zeroize pubkey still live in {len(live)} of {PK_WORDS} words, "
            f"first at index {live[0][0]}=0x{live[0][1]:08x}"
        )
        self.logger.info(
            "CHK-ZEROIZE PASS: VALID=0 and all %d pubkey words read 0 (read-gated, "
            "not a proven RAM wipe)",
            PK_WORDS,
        )

        flipped = cfg.flipped_seed(list(NIST_KG_SEED))
        pk2 = await self._keygen(abr, flipped, cfg.entropy, what="sensitivity-keygen")
        assert pk2 != pk, (
            "sensitivity keyGen returned the same pk as the NIST vector "
            f"(flip word {cfg.flip_word} bit {cfg.flip_bit} did not land)"
        )
        # A zeroed window differs from pk too, so require real key material.
        assert any(w != 0 for w in pk2), (
            "sensitivity keyGen returned an all-zero pubkey window; the inequality "
            "against the NIST vector is satisfied by a cleared window, not a new key"
        )
        self.logger.info(
            "CHK-SENSITIVITY PASS: flipped seed word %d bit %d produced a different public key",
            cfg.flip_word,
            cfg.flip_bit,
        )

        self.logger.info("abr mldsa keygen ALL CHECKS PASS")
