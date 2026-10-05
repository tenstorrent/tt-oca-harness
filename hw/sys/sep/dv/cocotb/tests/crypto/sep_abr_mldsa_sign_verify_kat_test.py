# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR ML-DSA-87 SIGN returns the ACVP signature; VERIFY accepts the good case, rejects the bad.

``sep_abr_mldsa_keygen_kat_test`` owns KEYGEN (0x1). ``MLDSA_CTRL.CTRL`` also
encodes SIGNING (0x2) and VERIFYING (0x3), and this leaf owns both, together
with the signature and verify-result windows they drive.

Both vectors are the ACVP external-mu groups, so ``MLDSA_CTRL.EXTERNAL_MU`` is
set and mu is written directly rather than a raw message. Signing is the
deterministic variant, so the signature is a fixed function of (sk, mu) and can
be compared word-for-word against the published value -- a randomised signature
could only be checked by verifying it, which is a weaker claim.

VERIFY is walked twice, with the ACVP case that must verify and the one that
must not. The RDL pass condition is ``MLDSA_VERIFY_RES`` equal to the first
part of the submitted signature (c~). An engine that copies each submitted c~
into the result register fails the rejecting case.

VALID is sticky and READY does not re-assert until a zeroize, so each command
is preceded by one. ML-KEM, the key-vault seed path and KEYGEN_SIGN (0x4) are
not claimed here.

RANDCFG: masking entropy comes from the run seed; the vectors are fixed.
no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_abr_nist import (
    NIST_SG_MU,
    NIST_SG_SIG,
    NIST_SG_SK,
    NIST_SV_BAD_MU,
    NIST_SV_BAD_PK,
    NIST_SV_BAD_SIG,
    NIST_SV_BAD_VERDICT,
    NIST_SV_OK_MU,
    NIST_SV_OK_PK,
    NIST_SV_OK_SIG,
    NIST_SV_OK_VERDICT,
)
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_EXTERNAL_MU,
    ABR_NAME0,
    ABR_NAME1,
    ABR_PRIVKEY_IN,
    ABR_PUBKEY,
    ABR_SIGNATURE,
    ABR_STATUS,
    ABR_VERIFY_RES,
    CMD_SIGN,
    CMD_VERIFY,
    CTRL_EXTERNAL_MU,
    CTRL_ZEROIZE,
    ERROR_INTERNAL_STS,
    IRQ_ABR_ERROR,
    SIG_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    VERIFY_RES_WORDS,
    SepAbr,
    SepAbrKeygenCfg,
)

# Sign is heavier than keygen; this is a backstop so a hang fails the wait
# rather than the simulation timeout.
_POLL_ITERS = 40000
_POLL_GAP = 200


@pyuvm.test()
class sep_abr_mldsa_sign_verify_kat_test(sep_base_test):
    """ML-DSA-87 SIGN against the ACVP signature, and VERIFY accept plus reject."""

    async def _irq_bit(self, idx: int) -> str:
        """One PIC aggregator bit as a character, so X is distinguishable from 0.

        Reads the bit string directly and returns what is on the wire, so the
        low-check failure message names an X/Z bit as such. Only ``"0"`` passes
        the low check and only ``"1"`` counts as an asserted error bit, so an
        unknown bit satisfies neither.
        """
        await RisingEdge(cocotb.top.clk_i)
        value = cocotb.top.sep_internal_interrupts_probe_o.value
        bits = getattr(value, "binstr", None) or str(value)
        return bits[len(bits) - 1 - idx]

    async def _assert_irq_low(self, idx: int, *, what: str) -> None:
        bit = await self._irq_bit(idx)
        assert bit == "0", (
            f"PIC [{idx}] reads '{bit}' {what}. An 'x' here is not a pass: the "
            "aggregator bit is undriven or unresolved, which is a different "
            "defect from a bit that is genuinely low."
        )

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

    async def _zeroize(self, abr: SepAbr, *, what: str) -> int:
        """VALID is sticky and READY stays low until a zeroize, so commands cannot
        be issued back to back. Returns the first STATUS read with VALID clear."""
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        st_z = await self._wait_status(abr, ST_VALID, 0, what=f"{what} post-zeroize VALID clear")
        await self._wait_status(abr, ST_READY, ST_READY, what=f"{what} post-zeroize READY")
        return st_z

    async def run_scenario(self) -> None:
        cfg = SepAbrKeygenCfg(self.random_seed())
        self.logger.info("abr mldsa sign/verify: %s", cfg.summary())

        await self.bring_up_no_cpu()
        abr = SepAbr(self)

        # Logged for the record, not graded: abr_reg.rdl declares NAME sw=r
        # with no reset, and no SEP document gives its value. A dead aperture
        # fails the signature compare against the published vector below.
        name0 = await abr.rd32(ABR_NAME0)
        name1 = await abr.rd32(ABR_NAME1)
        self.logger.info(
            "ABR ML-DSA identity words (information only): NAME0=0x%08x NAME1=0x%08x",
            name0,
            name1,
        )

        await abr.enable_notif()
        await self._assert_irq_low(IRQ_ABR_ERROR, what="before error_intr_trig")
        await abr.trigger_error()
        saw_err = False
        for _ in range(64):
            if await self._irq_bit(IRQ_ABR_ERROR) == "1":
                saw_err = True
                break
        assert saw_err, (
            f"PIC [{IRQ_ABR_ERROR}] stayed low after error_intr_trig "
            "(probe stuck-low / enable missed)"
        )
        err_st = await abr.error_state()
        assert err_st == ERROR_INTERNAL_STS, f"error_internal_sts=0x{err_st:x} after trigger"
        err_clr = await abr.w1c_error()
        assert err_clr == 0, f"error_internal_sts=0x{err_clr:x} after W1C"
        await self._assert_irq_low(IRQ_ABR_ERROR, what="after error_internal_sts W1C")
        self.logger.info(
            "CHK-PIC-ERROR PASS: [%d] 0->1 via error_intr_trig, error_internal_sts=0x%x "
            "after trigger, 0x%x after W1C",
            IRQ_ABR_ERROR,
            err_st,
            err_clr,
        )

        # --- CHK-SIGN ---------------------------------------------------------
        await self._wait_status(abr, ST_READY, ST_READY, what="pre-sign READY")
        await abr.write_words(ABR_PRIVKEY_IN, list(NIST_SG_SK))
        await abr.write_words(ABR_EXTERNAL_MU, list(NIST_SG_MU))
        await abr.write_words(ABR_ENTROPY, cfg.entropy)
        await abr.wr32(ABR_CTRL, CMD_SIGN | CTRL_EXTERNAL_MU)
        st = await self._wait_status(abr, ST_VALID, ST_VALID, what="sign VALID")
        assert (st & ST_ERROR) == 0, f"sign: VALID with ERROR (0x{st:08x})"

        sig = await abr.read_words(ABR_SIGNATURE, SIG_WORDS)
        # Length before value: zip() stops at the shorter list, so a short
        # readback would narrow the compare instead of failing it.
        assert len(sig) == len(NIST_SG_SIG), (
            f"CHK-SIGN FAIL: read {len(sig)} signature words, vector has {len(NIST_SG_SIG)}"
        )
        mismatch = next((i for i, (g, e) in enumerate(zip(sig, NIST_SG_SIG)) if g != e), None)
        assert mismatch is None, (
            f"CHK-SIGN FAIL: signature mismatch at word {mismatch} of {SIG_WORDS}: "
            f"got=0x{sig[mismatch]:08x} exp=0x{NIST_SG_SIG[mismatch]:08x}. Deterministic "
            "signing makes this a fixed function of the private key and mu, so a "
            "mismatch is a real failure and not a randomisation difference."
        )
        await self._assert_irq_low(IRQ_ABR_ERROR, what="after SIGN")
        self.logger.info(
            "CHK-SIGN PASS: %d-word signature matches the ACVP sigGen vector "
            "(deterministic, external mu)",
            SIG_WORDS,
        )

        # --- CHK-ZEROIZE ------------------------------------------------------
        # Read the window CHK-SIGN just read live, so the open read and the
        # closed read are on the same signature. The signature read port is
        # gated on the valid register and ZEROIZE also clears the signature
        # storage, so a zero window shows the signature is not readable,
        # NOT which of the two mechanisms closed it.
        st_z = await self._zeroize(abr, what="after sign")
        sig_z = await abr.read_words(ABR_SIGNATURE, SIG_WORDS)
        assert len(sig_z) == SIG_WORDS, (
            f"CHK-ZEROIZE FAIL: read {len(sig_z)} signature words after zeroize, "
            f"window is {SIG_WORDS}"
        )
        live = [(i, w) for i, w in enumerate(sig_z) if w != 0]
        assert not live, (
            f"CHK-ZEROIZE FAIL: post-zeroize signature still live in {len(live)} of "
            f"{SIG_WORDS} words, first at index {live[0][0]}=0x{live[0][1]:08x}"
        )
        self.logger.info(
            "CHK-ZEROIZE PASS: after SIGN, STATUS=0x%08x (VALID=0) and all %d "
            "signature words read 0, where %d of them read non-zero before the "
            "zeroize (read-gated, not a proven RAM wipe)",
            st_z,
            SIG_WORDS,
            sum(1 for w in sig if w != 0),
        )

        # --- CHK-VERIFY-ACCEPT and CHK-VERIFY-REJECT --------------------------
        # Walked as a pair from one helper so the two cases cannot drift apart:
        # the only difference between them is the vector and the expected
        # verdict.
        # Guard on which way round the pair is before the engine is asked
        # anything. sep_abr_nist already refuses two vectors with the same
        # verdict; what it cannot say is which of them is the accepting one, and
        # the two legs below are only named correctly if this holds.
        assert NIST_SV_OK_VERDICT == 1 and NIST_SV_BAD_VERDICT == 0, (
            "expected the ACVP sigVer pair as (accept, reject) = (1, 0), got "
            f"({NIST_SV_OK_VERDICT}, {NIST_SV_BAD_VERDICT}) -- the accept and "
            "reject legs below would be the wrong way round"
        )

        results = {}
        for tag, pk, mu, vsig, want in (
            ("accept", NIST_SV_OK_PK, NIST_SV_OK_MU, NIST_SV_OK_SIG, NIST_SV_OK_VERDICT),
            ("reject", NIST_SV_BAD_PK, NIST_SV_BAD_MU, NIST_SV_BAD_SIG, NIST_SV_BAD_VERDICT),
        ):
            await self._wait_status(abr, ST_READY, ST_READY, what=f"pre-verify-{tag} READY")
            await abr.write_words(ABR_PUBKEY, list(pk))
            await abr.write_words(ABR_EXTERNAL_MU, list(mu))
            await abr.write_words(ABR_SIGNATURE, list(vsig))
            await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_EXTERNAL_MU)
            st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"verify-{tag} VALID")
            assert (st & ST_ERROR) == 0, f"verify-{tag}: VALID with ERROR (0x{st:08x})"
            res = await abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)
            # Length before value: zip() stops at the shorter list.
            assert len(res) == VERIFY_RES_WORDS, (
                f"verify-{tag}: read {len(res)} VERIFY_RES words, RDL array is {VERIFY_RES_WORDS}"
            )
            c_tilde = list(vsig[:VERIFY_RES_WORDS])
            assert len(c_tilde) == VERIFY_RES_WORDS, (
                f"verify-{tag}: submitted signature is {len(vsig)} words, "
                f"shorter than c~ ({VERIFY_RES_WORDS})"
            )
            results[tag] = res
            mismatch = next(
                (i for i, (got, exp) in enumerate(zip(res, c_tilde)) if got != exp),
                None,
            )
            if want:
                assert mismatch is None, (
                    f"CHK-VERIFY-ACCEPT FAIL: MLDSA_VERIFY_RES differs from the "
                    f"submitted signature c~ at word {mismatch} of {VERIFY_RES_WORDS}: "
                    f"got=0x{res[mismatch]:08x} exp=0x{c_tilde[mismatch]:08x}"
                )
                self.logger.info(
                    "CHK-VERIFY-ACCEPT PASS: %d-word MLDSA_VERIFY_RES equals the "
                    "submitted signature c~ (RDL pass condition)",
                    VERIFY_RES_WORDS,
                )
            else:
                assert mismatch is not None, (
                    "CHK-VERIFY-REJECT FAIL: MLDSA_VERIFY_RES equals the submitted "
                    "signature c~, which is the RDL verified condition on a case "
                    "that must not verify"
                )
                self.logger.info(
                    "CHK-VERIFY-REJECT PASS: %d-word MLDSA_VERIFY_RES differs from "
                    "the submitted signature c~ (first mismatch at word %d: "
                    "0x%08x != 0x%08x)",
                    VERIFY_RES_WORDS,
                    mismatch,
                    res[mismatch],
                    c_tilde[mismatch],
                )
            await self._zeroize(abr, what=f"after verify-{tag}")

        assert results["accept"] != results["reject"], (
            "CHK-VERIFY-REJECT FAIL: accept and reject returned the same "
            f"{VERIFY_RES_WORDS}-word MLDSA_VERIFY_RES, so the result register "
            "is not updated per command"
        )
