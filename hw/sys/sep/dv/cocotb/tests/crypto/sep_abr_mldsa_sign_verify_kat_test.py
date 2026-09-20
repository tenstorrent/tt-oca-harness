# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-DSA-87 SIGN and VERIFY NIST KAT on the ABR aperture.

``sep_abr_mldsa_keygen_kat_test`` owns KEYGEN (0x1). ``MLDSA_CTRL.CTRL`` also
encodes SIGNING (0x2) and VERIFYING (0x3), and this leaf owns both, together
with the signature and verify-result windows they drive.

Both vectors are the ACVP external-mu groups, so ``MLDSA_CTRL.EXTERNAL_MU`` is
set and mu is written directly rather than a raw message. Signing is the
deterministic variant, so the signature is a fixed function of (sk, mu) and can
be compared word-for-word against the published value -- a randomised signature
could only be checked by verifying it, which is a weaker claim.

VERIFY is walked twice, with the ACVP case that must verify and the one that
must not. The rejecting case is the load-bearing half: an engine that reported
success unconditionally would pass the accepting case alone.

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
    IRQ_ABR_ERROR,
    NAME0_EXP,
    NAME1_EXP,
    SIG_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
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

        ``sep_base_test.rd`` resolves an unknown bit to 0 per bit, which is the
        passing value for the checks below -- an X on the probe would read as a
        clean low. Its docstring says a caller that must tell the two apart
        cannot use it, so this reads the bit string directly and returns what is
        really on the wire.
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

    async def _zeroize(self, abr: SepAbr, *, what: str) -> None:
        """VALID is sticky and READY stays low until a zeroize, so commands cannot
        be issued back to back."""
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_VALID, 0, what=f"{what} post-zeroize VALID clear")
        await self._wait_status(abr, ST_READY, ST_READY, what=f"{what} post-zeroize READY")

    async def run_scenario(self) -> None:
        cfg = SepAbrKeygenCfg(self.random_seed())
        self.logger.info("abr mldsa sign/verify: %s", cfg.summary())

        await self.bring_up_no_cpu()
        abr = SepAbr(self)

        # Same identity gate the keygen leaf uses: if the aperture were dead
        # every window below would read zero and the compares would be against
        # a silent bus.
        name0 = await abr.rd32(ABR_NAME0)
        name1 = await abr.rd32(ABR_NAME1)
        assert name0 == NAME0_EXP and name1 == NAME1_EXP, (
            f"MLDSA NAME 0x{name0:08x}_0x{name1:08x}, "
            f"expected 0x{NAME0_EXP:08x}_0x{NAME1_EXP:08x} (MLDSA-87)"
        )
        self.logger.info("CHK-NAME PASS: NAME0=0x%08x NAME1=0x%08x (MLDSA-87)", name0, name1)

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
        assert err_st & 1, f"error_internal_sts=0x{err_st:x} after trigger"
        err_st = await abr.w1c_error()
        assert (err_st & 1) == 0, f"error_internal_sts=0x{err_st:x} after W1C"
        await self._assert_irq_low(IRQ_ABR_ERROR, what="after error_internal_sts W1C")
        self.logger.info(
            "CHK-PIC-ERROR PASS: [%d] 0->1 via error_intr_trig, W1C readback 0",
            IRQ_ABR_ERROR,
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

        await self._zeroize(abr, what="after sign")

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
            res = await abr.rd32(ABR_VERIFY_RES)
            results[tag] = res
            self.logger.info(
                "verify-%s: MLDSA_VERIFY_RES=0x%08x (ACVP testPassed=%d)", tag, res, want
            )
            await self._zeroize(abr, what=f"after verify-{tag}")

        # The engine signals the result in MLDSA_VERIFY_RES. What matters, and
        # what a DUT can fail, is that the two cases are DISTINGUISHED: the
        # accepting vector and the rejecting vector must not produce the same
        # value. Pinning an absolute encoding here would be transcribing a
        # value the register description does not state.
        assert results["accept"] != results["reject"], (
            "CHK-VERIFY-REJECT FAIL: the ACVP case that must verify and the case "
            f"that must not both returned MLDSA_VERIFY_RES=0x{results['accept']:08x}. "
            "The engine is not distinguishing a good signature from a bad one, or "
            "the result register is not being updated per command."
        )
        assert results["accept"] != 0, (
            "CHK-VERIFY-ACCEPT FAIL: the accepting ACVP case returned "
            "MLDSA_VERIFY_RES=0, which is the same thing an engine that never ran "
            "would report"
        )
        self.logger.info(
            "CHK-VERIFY-ACCEPT PASS: the ACVP case that must verify returned a "
            "non-zero MLDSA_VERIFY_RES (0x%08x)",
            results["accept"],
        )
        self.logger.info(
            "CHK-VERIFY-REJECT PASS: the ACVP case that must not verify returned a "
            "different MLDSA_VERIFY_RES (0x%08x != 0x%08x), so the accept result is "
            "not an unconditional success",
            results["reject"],
            results["accept"],
        )

        # --- CHK-ZEROIZE ------------------------------------------------------
        # Same contract class and same stated limit as the keygen leaf: the
        # signature read port is gated on the valid register, so a zero window
        # shows the read port is closed, NOT that the RAM was wiped.
        sig_z = await abr.read_words(ABR_SIGNATURE, SIG_WORDS)
        live = [(i, w) for i, w in enumerate(sig_z) if w != 0]
        assert not live, (
            f"CHK-ZEROIZE FAIL: post-zeroize signature still live in {len(live)} of "
            f"{SIG_WORDS} words, first at index {live[0][0]}=0x{live[0][1]:08x}"
        )
        self.logger.info(
            "CHK-ZEROIZE PASS: all %d signature words read 0 after zeroize "
            "(read-gated, not a proven RAM wipe)",
            SIG_WORDS,
        )
