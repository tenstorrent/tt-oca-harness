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
coefficient is in range and the hint encoding is malformed, so the engine gets
past its z check and must reject at the hint decode. A rejected signature
leaves ``MLDSA_VERIFY_RES`` at the inverted c~ that accepting VERIFY preloads,
which is neither the pass value (c~) nor a recomputed c~'; a hint the engine
accepted would show as one of those two.

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


@pyuvm.test()
class sep_abr_mldsa_hint_reject_kat_test(sep_base_test):
    """ML-DSA-87 VERIFY on the NIST malformed-hint cases, after one that must verify."""

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

    async def _stream(self, abr: SepAbr, words: list[int], nbytes: int, *, what: str) -> None:
        """Stream a message once the engine asks for it. The strobe goes before each
        word, and the first strobe other than 0xF ends the stream, so a whole-word
        message ends with strobe 0 and a dummy word."""
        for _ in range(_POLL_ITERS):
            st = await abr.rd32(ABR_STATUS)
            if st & ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR before MSG_STREAM_READY (0x{st:08x})")
            if st & ST_MSG_STREAM_READY:
                break
            # VALID first means the engine rejected before the message: the z
            # check, which the generator has ruled out for these cases.
            assert not st & ST_VALID, (
                f"{what}: VALID before MSG_STREAM_READY (0x{st:08x}); the engine "
                "rejected before asking for the message, so the hint decode never ran"
            )
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        else:
            raise AssertionError(f"{what}: MSG_STREAM_READY never set in {_POLL_ITERS} polls")
        whole = nbytes // 4
        for w in words[:whole]:
            await abr.wr32(ABR_MSG_STROBE, STROBE_FULL)
            await abr.wr32(ABR_MSG, w)
        tail = nbytes % 4
        await abr.wr32(ABR_MSG_STROBE, (1 << tail) - 1)
        await abr.wr32(ABR_MSG, words[whole] if tail else 0)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        abr = SepAbr(self)

        for case in NIST_HINT_CASES:
            what = f"tcId {case.tcid} ({case.interface})"
            c_tilde = list(case.sig[:VERIFY_RES_WORDS])
            inverse = [~w & 0xFFFF_FFFF for w in c_tilde]

            await self._zeroize(abr, what=f"before {what}")
            await abr.write_words(ABR_PUBKEY, case.pk)
            await abr.write_words(ABR_SIGNATURE, case.sig)
            if case.external_mu:
                await abr.write_words(ABR_EXTERNAL_MU, case.mu)
                await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_EXTERNAL_MU)
            else:
                await abr.wr32(ABR_CTX_CONFIG, case.ctx_bytes)
                await abr.write_words(ABR_CTX, case.ctx)
                await abr.wr32(ABR_CTRL, CMD_VERIFY | CTRL_STREAM_MSG)
                # The engine waits for the message, so the preload is still there.
                pre = await abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)
                assert pre == inverse, (
                    f"CHK-HINT-PRELOAD FAIL: {what}: MLDSA_VERIFY_RES is not the "
                    "inverted c~ after VERIFY was accepted, so the command did not land"
                )
                await self._stream(abr, case.msg, case.msg_bytes, what=what)

            st = await self._wait_status(abr, ST_VALID, ST_VALID, what=f"{what} VALID")
            assert not st & ST_ERROR, f"{what}: VALID with ERROR (0x{st:08x})"
            res = await abr.read_words(ABR_VERIFY_RES, VERIFY_RES_WORDS)

            if case.verdict:
                assert res == c_tilde, (
                    f"CHK-HINT-CONTROL FAIL: {what} must verify, but MLDSA_VERIFY_RES is "
                    f"{'the inverted c~' if res == inverse else 'neither c~ nor its inverse'}"
                )
                self.logger.info(
                    "CHK-HINT-CONTROL PASS: %s verifies: %d-byte message streamed, "
                    "%d-byte context, MLDSA_VERIFY_RES equals c~",
                    what,
                    case.msg_bytes,
                    case.ctx_bytes,
                )
            else:
                assert res != c_tilde, (
                    f"CHK-HINT-REJECT FAIL: {what}: MLDSA_VERIFY_RES equals c~, so the "
                    "engine accepted a signature whose hint encoding FIPS 204 rejects"
                )
                assert res == inverse, (
                    f"CHK-HINT-REJECT FAIL: {what}: MLDSA_VERIFY_RES is a recomputed c~' "
                    "rather than the inverted c~, so the engine decoded the malformed "
                    "hint and finished the verify instead of rejecting it"
                )
                self.logger.info(
                    "CHK-HINT-REJECT PASS: %s rejected at the hint decode: "
                    "MLDSA_VERIFY_RES is the inverted c~%s",
                    what,
                    "" if case.external_mu else f" after a {case.msg_bytes}-byte stream",
                )

        await self._zeroize(abr, what="after the last case")
        self.logger.info(
            "CHK-HINT-REJECT: %d malformed-hint cases rejected, %d pure and %d external mu",
            len(NIST_HINT_CASES) - 1,
            sum(1 for c in NIST_HINT_CASES[1:] if not c.external_mu),
            sum(1 for c in NIST_HINT_CASES[1:] if c.external_mu),
        )
