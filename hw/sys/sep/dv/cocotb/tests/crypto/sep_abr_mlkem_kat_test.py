# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Adams Bridge ML-KEM-1024 keyGen / encaps / decaps NIST KAT on the ABR aperture.

The ML-DSA leaves own MLDSA_CTRL. ML-KEM is a separate register block in the
same aperture with its own MLKEM_CTRL command field, and this leaf owns it: the
encapsulation key, decapsulation key, ciphertext and shared-key windows are
driven and read here.

Three legal commands are walked, each against the published ACVP value:

  * KEYGEN  -- the two seeds in, ek and dk compared word-for-word.
  * ENCAPS  -- ek plus the message randomness m fix the ciphertext and the
    shared key, so both are compared. Randomness is supplied over the bus,
    which is what makes encaps a known answer rather than a round trip.
  * DECAPS  -- walked twice: the ACVP case that decapsulates normally, and the
    "modified ciphertext" case. FIPS-203 uses implicit rejection, so the bad
    ciphertext does NOT raise an error; it yields a different shared key, and
    ACVP publishes that key too. Both are graded by value.

The rejecting decaps case is the load-bearing half. An engine that skipped
implicit rejection, or that returned a cached shared key, passes the accepting
case and fails that one.

Two false-pass hazards this leaf has to handle, both from the vendor register
description: MLKEM_CTRL is writable only while STATUS.READY is set, so a command
issued to a busy engine is dropped silently; and the key/ciphertext read ports
are gated on the valid register, so they read zero before a command completes.

ML-DSA, the key-vault seed path and KEYGEN+DECAPS (0x4) are not claimed here.

RANDCFG: none. Every input is a fixed published vector.
no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_abr_kem_nist import (
    NIST_KEM_DEC_BAD_C,
    NIST_KEM_DEC_BAD_DK,
    NIST_KEM_DEC_BAD_K,
    NIST_KEM_DEC_OK_C,
    NIST_KEM_DEC_OK_DK,
    NIST_KEM_DEC_OK_K,
    NIST_KEM_ENC_C,
    NIST_KEM_ENC_EK,
    NIST_KEM_ENC_K,
    NIST_KEM_ENC_M,
    NIST_KEM_KG_D,
    NIST_KEM_KG_DK,
    NIST_KEM_KG_EK,
    NIST_KEM_KG_Z,
)
from sep_base_test import sep_base_test
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_DECAPS,
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_DK_WORDS,
    KEM_EK_WORDS,
    KEM_K_WORDS,
    KEM_NAME0_EXP,
    KEM_NAME1_EXP,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_DECAPS_KEY,
    MLKEM_ENCAPS_KEY,
    MLKEM_MSG,
    MLKEM_NAME0,
    MLKEM_NAME1,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_SHARED_KEY,
    MLKEM_STATUS,
    SepAbrMlkem,
)

# Backstop so a wedged engine fails the wait with a named contract rather than
# running into the simulation timeout.
_POLL_ITERS = 40000
_POLL_GAP = 200


@pyuvm.test()
class sep_abr_mlkem_kat_test(sep_base_test):
    """ML-KEM-1024 keyGen, encaps, and decaps accept plus implicit rejection."""

    async def _wait_status(self, kem, mask: int, expect: int, *, what: str) -> int:
        for _ in range(_POLL_ITERS):
            st = await kem.rd32(MLKEM_STATUS)
            if (st & mask) == expect:
                return st
            if st & KEM_ST_ERROR:
                raise AssertionError(f"{what}: STATUS.ERROR set (0x{st:08x})")
            await ClockCycles(cocotb.top.clk_i, _POLL_GAP)
        raise AssertionError(
            f"{what}: STATUS mask 0x{mask:x} never 0x{expect:x} in {_POLL_ITERS} polls"
        )

    async def _command(self, kem, cmd: int, *, what: str) -> int:
        """Issue one MLKEM_CTRL command and wait for it to complete.

        The READY wait is not politeness: MLKEM_CTRL is gated on READY in the
        register description, so a write issued while the engine is busy is
        dropped and the stale VALID would be read as this command's completion.
        """
        await self._wait_status(kem, KEM_ST_READY, KEM_ST_READY, what=f"{what} pre-command READY")
        await kem.wr32(MLKEM_CTRL, cmd)
        st = await self._wait_status(kem, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID")
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        return st

    async def _zeroize(self, kem, *, what: str) -> None:
        await kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._wait_status(kem, KEM_ST_VALID, 0, what=f"{what} post-zeroize VALID clear")
        await self._wait_status(kem, KEM_ST_READY, KEM_ST_READY, what=f"{what} post-zeroize READY")

    @staticmethod
    def _first_mismatch(got: list[int], exp: list[int]) -> int | None:
        return next((i for i, (g, e) in enumerate(zip(got, exp)) if g != e), None)

    def _compare(self, got: list[int], exp: list[int], *, chk: str, what: str) -> None:
        # Length first. zip() stops at the shorter list, so without this a short
        # readback would silently narrow the compare and an empty one would pass
        # with nothing examined.
        assert len(got) == len(exp), (
            f"{chk} FAIL: {what} is {len(got)} words, expected {len(exp)} -- the "
            "readback and the vector disagree on length, so the value compare "
            "below would only cover the overlap"
        )
        bad = self._first_mismatch(got, exp)
        assert bad is None, (
            f"{chk} FAIL: {what} differs from the ACVP vector at word {bad} of "
            f"{len(exp)}: got=0x{got[bad]:08x} exp=0x{exp[bad]:08x}"
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        kem = SepAbrMlkem(self)

        # Identity gate. Every window compare below reads back over this same
        # aperture, so a dead decode would make them all compares against zero.
        name0 = await kem.rd32(MLKEM_NAME0)
        name1 = await kem.rd32(MLKEM_NAME1)
        assert name0 == KEM_NAME0_EXP and name1 == KEM_NAME1_EXP, (
            f"MLKEM NAME 0x{name0:08x}_0x{name1:08x}, "
            f"expected 0x{KEM_NAME0_EXP:08x}_0x{KEM_NAME1_EXP:08x} (KEM-1024)"
        )
        self.logger.info("CHK-KEM-NAME PASS: NAME0=0x%08x NAME1=0x%08x (KEM-1024)", name0, name1)

        # --- CHK-KEM-KEYGEN ---------------------------------------------------
        await kem.write_words(MLKEM_SEED_D, list(NIST_KEM_KG_D))
        await kem.write_words(MLKEM_SEED_Z, list(NIST_KEM_KG_Z))
        await self._command(kem, KEM_CMD_KEYGEN, what="keygen")

        ek = await kem.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        dk = await kem.read_words(MLKEM_DECAPS_KEY, KEM_DK_WORDS)
        self._compare(ek, NIST_KEM_KG_EK, chk="CHK-KEM-KEYGEN", what="the encapsulation key")
        self._compare(dk, NIST_KEM_KG_DK, chk="CHK-KEM-KEYGEN", what="the decapsulation key")
        self.logger.info(
            "CHK-KEM-KEYGEN PASS: %d-word ek and %d-word dk both match the ACVP "
            "keyGen vector for seeds (d, z)",
            KEM_EK_WORDS,
            KEM_DK_WORDS,
        )
        await self._zeroize(kem, what="after keygen")

        # --- CHK-KEM-ENCAPS ---------------------------------------------------
        # m is written over the bus, which is what makes the ciphertext a fixed
        # function of published inputs. With engine-chosen randomness the only
        # available check would be a decaps round trip, which is weaker.
        await kem.write_words(MLKEM_ENCAPS_KEY, list(NIST_KEM_ENC_EK))
        await kem.write_words(MLKEM_MSG, list(NIST_KEM_ENC_M))
        await self._command(kem, KEM_CMD_ENCAPS, what="encaps")

        ct = await kem.read_words(MLKEM_CIPHERTEXT, KEM_CT_WORDS)
        k_enc = await kem.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        self._compare(ct, NIST_KEM_ENC_C, chk="CHK-KEM-ENCAPS", what="the ciphertext")
        self._compare(k_enc, NIST_KEM_ENC_K, chk="CHK-KEM-ENCAPS", what="the shared key")
        self.logger.info(
            "CHK-KEM-ENCAPS PASS: %d-word ciphertext and the shared key both match "
            "the ACVP encaps vector for (ek, m)",
            KEM_CT_WORDS,
        )
        await self._zeroize(kem, what="after encaps")

        # --- CHK-KEM-DECAPS and CHK-KEM-DECAPS-REJECT -------------------------
        # Walked from one helper so the accepting and rejecting cases cannot
        # drift apart: only the vector changes between them.
        shared = {}
        for tag, dk_in, ct_in, k_exp, chk in (
            ("accept", NIST_KEM_DEC_OK_DK, NIST_KEM_DEC_OK_C, NIST_KEM_DEC_OK_K, "CHK-KEM-DECAPS"),
            (
                "reject",
                NIST_KEM_DEC_BAD_DK,
                NIST_KEM_DEC_BAD_C,
                NIST_KEM_DEC_BAD_K,
                "CHK-KEM-DECAPS-REJECT",
            ),
        ):
            await kem.write_words(MLKEM_DECAPS_KEY, list(dk_in))
            await kem.write_words(MLKEM_CIPHERTEXT, list(ct_in))
            await self._command(kem, KEM_CMD_DECAPS, what=f"decaps-{tag}")
            k = await kem.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
            shared[tag] = k
            self._compare(k, list(k_exp), chk=chk, what=f"the decaps-{tag} shared key")
            await self._zeroize(kem, what=f"after decaps-{tag}")

        # Each case already matched its own published key, so this cannot fail
        # unless the vectors themselves collide -- which the loader refuses at
        # import. It is asserted anyway so the log line below states something
        # this test checked rather than something a reader must infer.
        assert shared["reject"] != shared["accept"], (
            "CHK-KEM-DECAPS-REJECT FAIL: the valid and modified-ciphertext cases "
            "returned the same shared key, so implicit rejection is not observable"
        )
        self.logger.info(
            "CHK-KEM-DECAPS PASS: the ACVP valid-decapsulation case recovered the "
            "published shared key"
        )
        self.logger.info(
            "CHK-KEM-DECAPS-REJECT PASS: the modified-ciphertext case returned the "
            "published implicit-rejection key, which is a different value (0x%08x "
            "vs 0x%08x in word 0) -- the engine derives it rather than reporting "
            "success or reusing the last key",
            shared["reject"][0],
            shared["accept"][0],
        )

        # --- CHK-KEM-ZEROIZE --------------------------------------------------
        # Same contract class and the same stated limit as the ML-DSA leaves:
        # the read port is gated on the valid register, so a zero window shows
        # the read port is closed, NOT that the RAM was wiped.
        k_z = await kem.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        live = [(i, w) for i, w in enumerate(k_z) if w != 0]
        assert not live, (
            f"CHK-KEM-ZEROIZE FAIL: shared key still live in {len(live)} of "
            f"{KEM_K_WORDS} words, first at index {live[0][0]}=0x{live[0][1]:08x}"
        )
        self.logger.info(
            "CHK-KEM-ZEROIZE PASS: all %d shared-key words read 0 after zeroize "
            "(read-gated, not a proven RAM wipe)",
            KEM_K_WORDS,
        )
