# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR ML-DSA-87 VERIFY rejects every NIST sigVer case with a malformed hint encoding.

FIPS 204 HintBitUnpack (Algorithm 21) rejects a hint whose per-polynomial end
indices decrease or exceed omega, whose indices within one polynomial do not
strictly increase, or whose unused slots are not zero. An encoding the engine
accepted anyway would give one signature a second valid encoding. This leaf
runs every ML-DSA-87 sigVer case the NIST ACVP-Server marks "modified
signature - hint" through the engine, on both interfaces the SEP drives: pure
ML-DSA with a context (tgId 5), whose message is streamed through
``MLDSA_MSG[0]`` with ``MLDSA_MSG_STROBE``, and external mu (tgId 11).

The generator checks each hint case independently of the ACVP verdict: every z
coefficient is in range and the hint encoding is malformed. The graded reject
is the register contract: a signature verifies if and only if
``MLDSA_VERIFY_RES`` equals c~ (abr_reg.rdl, MLDSA_VERIFY_RES), so a reject
case passes when ``MLDSA_VERIFY_RES`` differs from c~. No spec states when the
engine rejects relative to the message stream or what ``MLDSA_VERIFY_RES``
holds after a reject, so the leaf logs both as OBS lines and grades neither.

Case 0 is a pure-with-context signature that must verify, run first: the
streamed message and the context are new to this aperture's DV, and a stream or
context fault fails there on a known answer rather than reading as a reject.

VALID is sticky and READY does not re-assert until a zeroize, so each command
is preceded by one. no_cpu / +skip_fuse_sense; the vectors are fixed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_abr_nist import NIST_HINT_CASES
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_abr_reject_class
from env.sep_spec_tables import abr_field_mask, abr_off
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_BASE,
    ABR_CTRL,
    ABR_EXTERNAL_MU,
    ABR_MSG,
    ABR_PUBKEY,
    ABR_SIGNATURE,
    ABR_STATUS,
    ABR_VERIFY_RES,
    CMD_VERIFY,
    CTRL_EXTERNAL_MU,
    CTRL_ZEROIZE,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    VERIFY_RES_WORDS,
    SepAbr,
)

ABR_MSG_STROBE = ABR_BASE + abr_off("MLDSA_MSG_STROBE")
ABR_CTX_CONFIG = ABR_BASE + abr_off("MLDSA_CTX_CONFIG")
ABR_CTX = ABR_BASE + abr_off("MLDSA_CTX")
CTRL_STREAM_MSG = abr_field_mask("MLDSA_CTRL", "STREAM_MSG")
ST_MSG_STREAM_READY = abr_field_mask("MLDSA_STATUS", "MSG_STREAM_READY")
STROBE_FULL = abr_field_mask("MLDSA_MSG_STROBE", "STROBE")

# Backstop so a hang fails the wait rather than the simulation timeout.
_POLL_ITERS = 40000
_POLL_GAP = 200

TEST = "sep_abr_mldsa_hint_reject_kat_test"
# FCOV stimulus label of sep_abr_completion_cg cp_verify_outcome for an ACVP
# "modified signature - hint" row (env/sep_fcov_gate.py, set_abr_reject_class).
_REJECT_CLASS_HINT = 3


@pyuvm.test()
class sep_abr_mldsa_hint_reject_kat_test(sep_base_test):
    """ML-DSA-87 VERIFY on the NIST malformed-hint cases, after one that must verify."""

    required_evidence = ("CHK-HINT-VALID", "CHK-HINT-CONTROL", "CHK-HINT-REJECT")

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
        await abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        await self._wait_status(abr, ST_VALID, 0, what=f"{what} post-zeroize VALID clear")
        await self._wait_status(abr, ST_READY, ST_READY, what=f"{what} post-zeroize READY")

    async def _stream(self, abr: SepAbr, words: list[int], nbytes: int, *, what: str) -> bool:
        """Stream a message once the engine asks for it, and return True. The strobe
        goes before each word, and the first strobe other than 0xF ends the stream,
        so a whole-word message ends with strobe 0 and a dummy word.

        VALID before MSG_STREAM_READY means the engine rejected the signature
        before asking for the message (hw/sys/sep/bootrom/prod/doc/abr-mldsa-driver.adoc:73-74);
        then nothing is streamed and the return is False."""
        for _ in range(_POLL_ITERS):
            st = await abr.rd32(ABR_STATUS)
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR before MSG_STREAM_READY (0x{st:08x})")
            if st & ST_MSG_STREAM_READY:
                break
            if st & ST_VALID:
                return False
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        else:
            raise AssertionError(
                f"{what}: neither MSG_STREAM_READY nor VALID set in {_POLL_ITERS} polls"
            )
        whole = nbytes // 4
        for w in words[:whole]:
            await abr.wr32(ABR_MSG_STROBE, STROBE_FULL)
            await abr.wr32(ABR_MSG, w)
        tail = nbytes % 4
        await abr.wr32(ABR_MSG_STROBE, (1 << tail) - 1)
        await abr.wr32(ABR_MSG, words[whole] if tail else 0)
        return True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        abr = SepAbr(self)
        n_control = n_pure = n_ext = 0

        open_graded_window(TEST, self.logger)
        for case in NIST_HINT_CASES:
            what = f"tcId {case.tcid} ({case.interface})"
            c_tilde = list(case.sig[:VERIFY_RES_WORDS])
            inverse = [~w & 0xFFFF_FFFF for w in c_tilde]
            # The sampler compares every word of one VERIFY_RES read pass with c~
            # and keeps a difference until the next VERIFY, so a pass that follows
            # the preload read would count the preload. Only the external-mu
            # reject cases, which read VERIFY_RES once, carry the stimulus label.
            label = not case.verdict and case.external_mu

            await self._zeroize(abr, what=f"before {what}")
            await abr.write_words(ABR_PUBKEY, case.pk)
            await abr.write_words(ABR_SIGNATURE, case.sig)
            if label:
                set_abr_reject_class(_REJECT_CLASS_HINT, self.logger)
            streamed = None
            if case.external_mu:
                await abr.write_words(ABR_EXTERNAL_MU, case.mu)
                await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_EXTERNAL_MU)
            else:
                await abr.wr32(ABR_CTX_CONFIG, case.ctx_bytes)
                await abr.write_words(ABR_CTX, case.ctx)
                await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_STREAM_MSG)
                # No hardware spec states what MLDSA_VERIFY_RES holds once VERIFY is
                # accepted, so the value is logged, not graded.
                pre = await abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)
                self.logger.info(
                    "OBS-HINT-PRELOAD: %s: MLDSA_VERIFY_RES after VERIFY accept is %s",
                    what,
                    "~c~" if pre == inverse else ("0" if not any(pre) else "other"),
                )
                streamed = await self._stream(abr, case.msg, case.msg_bytes, what=what)

            # VALID rises only when the accelerator ran the command, so a VERIFY that
            # did not land fails here rather than passing as a reject.
            st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"{what} VALID")
            assert not st & ST_ERROR, f"{what}: VALID with ERROR (0x{st:08x})"
            self.logger.info("CHK-HINT-VALID PASS: %s: VALID rose after VERIFY", what)
            res = await abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)
            if label:
                set_abr_reject_class(0, self.logger)

            if case.verdict:
                assert res == c_tilde, (
                    f"CHK-HINT-CONTROL FAIL: {what} must verify, but MLDSA_VERIFY_RES is "
                    f"{'the inverted c~' if res == inverse else 'neither c~ nor its inverse'}"
                    f"{'' if streamed is not False else '; VALID rose before MSG_STREAM_READY'}"
                )
                self.logger.info(
                    "CHK-HINT-CONTROL PASS: %s verifies: %d-byte message streamed, "
                    "%d-byte context, MLDSA_VERIFY_RES equals c~",
                    what,
                    case.msg_bytes,
                    case.ctx_bytes,
                )
                n_control += 1
            else:
                assert res != c_tilde, (
                    f"CHK-HINT-REJECT FAIL: {what}: MLDSA_VERIFY_RES equals c~, so the "
                    "engine accepted a signature whose hint encoding FIPS 204 rejects"
                )
                if res == inverse:
                    res_class = "preload"
                elif not any(res):
                    res_class = "zero"
                else:
                    res_class = "other"
                if streamed is not None:
                    self.logger.info(
                        "OBS-HINT-REJECT-TIMING: %s timing=%s msg_bytes=%d",
                        what,
                        "late" if streamed else "early",
                        case.msg_bytes,
                    )
                self.logger.info(
                    "OBS-HINT-REJECT-RES: %s res=%s verify_res=%s",
                    what,
                    res_class,
                    "".join(f"{w:08x}" for w in res),
                )
                self.logger.info(
                    "CHK-HINT-REJECT PASS: %s rejected: MLDSA_VERIFY_RES differs from c~",
                    what,
                )
                if case.external_mu:
                    n_ext += 1
                else:
                    n_pure += 1

        await self._zeroize(abr, what="after the last case")
        close_graded_window(self.logger)
        assert n_control + n_pure + n_ext == len(NIST_HINT_CASES), (
            f"ran {n_control + n_pure + n_ext} of {len(NIST_HINT_CASES)} cases"
        )
        self.logger.info(
            "CHK-HINT-REJECT: %d malformed-hint cases rejected, %d pure and %d external mu",
            n_pure + n_ext,
            n_pure,
            n_ext,
        )
