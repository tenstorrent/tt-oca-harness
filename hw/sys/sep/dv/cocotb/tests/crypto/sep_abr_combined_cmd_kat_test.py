# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ABR ML-KEM-1024 KEYGEN+DECAPS returns the shared key of an ENCAPS against the same key pair.

Contract (``integration/rdl/sep/abr_reg.rdl``: ``MLKEM_CTRL.CTRL`` 100 is
KEYGEN+DECAPS, ``MLKEM_SEED_D`` / ``MLKEM_SEED_Z`` are the keyGen seeds,
``MLKEM_CIPHERTEXT`` is the ciphertext input of a decapsulation,
``MLKEM_SHARED_KEY`` is the output shared key; FIPS 203 correctness: for a key
pair (ek, dk) from ML-KEM.KeyGen(d, z), ML-KEM.Decaps(dk, c) returns the K of
ML-KEM.Encaps(ek)).

Self-consistency compare, not a golden. The seeds d, z and the encapsulation
key ek are one published NIST ACVP ML-KEM-1024 keyGen vector
(``env/sep_abr_kem_nist.py``). A single-step ENCAPS against that ek, with the
message m of the ACVP encaps vector, gives the ciphertext c and the key K. No
ACVP vector publishes K for this (ek, m) pair, so K is a DUT output. The leaf
then zeroizes and resets ABR, writes d, z and c, issues KEYGEN+DECAPS, and
requires ``MLKEM_SHARED_KEY`` to equal K. Both sides of the compare are DUT
outputs. The single-step ENCAPS is stimulus only; ``sep_abr_mlkem_kat_test``
grades ENCAPS against the ACVP vector.

Write order of KEYGEN+DECAPS: seeds d and z, then the ciphertext, then the
command, as the KEYGEN+DECAPS cell of ``sep_abr_command_matrix_rand_test``
writes them. The register description does not state an order.

Checkers:
  CHK-ABR-KEYGEN-DECAPS-SELFCONSIST  all 8 words of MLKEM_SHARED_KEY after
                    KEYGEN+DECAPS equal the K of the ENCAPS.
  CHK-ABR-KEYGEN-DECAPS-REJECT  after KEYGEN+DECAPS on the same z and c with
                    bit 0 of seed word d[0] flipped, all 8 words of
                    MLKEM_SHARED_KEY equal the implicit-rejection key
                    J(z || c) = SHAKE256(z || c, 256) of FIPS 203. This compare has a
                    golden: the standard function of the written z and c.

Controls (a false control logs CTRL-MISSING and fails the leaf):
  CTRL-ABR-ENCAPS-K-NONZERO  the K of the ENCAPS has a non-zero word, so a
                    window that reads 0 cannot match it.
  CTRL-ABR-SHARED-KEY-PRE    MLKEM_SHARED_KEY differs from K immediately before
                    the KEYGEN+DECAPS command write, after a ZEROIZE and an ABR
                    reset, so a K that stays in the window does not match.
  CTRL-ABR-VALID-PRE         STATUS.VALID reads 0 at the READY read before each
                    ML-KEM command write, so the VALID wait sees this command.

Observations (not graded; ``SEP_VPLAN.adoc`` Blocked features: the text does
not state which output windows a combined command fills):
  OBS-ABR-ENCAPS-STIMULUS     the K and the first ciphertext word of the ENCAPS.
  OBS-ABR-KEYGEN-DECAPS-KEY   word-match counts of MLKEM_ENCAPS_KEY and
                    MLKEM_DECAPS_KEY after KEYGEN+DECAPS against the ACVP ek, dk.
  OBS-ABR-KEYGEN-SIGN-KEY     word-match count of MLDSA_PUBKEY after one
                    ML-DSA-87 KEYGEN+SIGN on the ACVP keyGen seed against the
                    ACVP pk. The signature is not checked.

STATUS.ERROR is logged in an ``obs_error`` field and not graded. Waits are
bounded. A timeout in the ML-KEM chain logs the check as FAIL with
``reason=timeout``, resets ABR and continues with the ML-DSA observation; the
leaf fails at the end. This leaf scores no FCOV bin and opens no graded window.

RANDCFG: the ML-DSA masking entropy words come from the run seed
(``SepAbrKeygenCfg``, ``SepSeededRng``); no expected value depends on them.
Every other input is a fixed published vector.
no_cpu (``lsu_stub_all_live``) / +skip_fuse_sense.
"""

from __future__ import annotations

import hashlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_abr_kem_nist import (
    NIST_KEM_ENC_M,
    NIST_KEM_KG_D,
    NIST_KEM_KG_DK,
    NIST_KEM_KG_EK,
    NIST_KEM_KG_Z,
)
from env.sep_abr_nist import NIST_KG_PK, NIST_KG_SEED, NIST_SG_MU
from env.sep_chk_log import SepChkLog
from env.sep_spec_tables import abr_ctrl_cmd
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import (
    ABR_CTRL,
    ABR_ENTROPY,
    ABR_EXTERNAL_MU,
    ABR_PUBKEY,
    ABR_SEED,
    ABR_STATUS,
    CTRL_EXTERNAL_MU,
    CTRL_ZEROIZE,
    PK_WORDS,
    ST_ERROR,
    ST_READY,
    ST_VALID,
    SepAbr,
    SepAbrKeygenCfg,
)
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN_DECAPS,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_DK_WORDS,
    KEM_EK_WORDS,
    KEM_K_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_DECAPS_KEY,
    MLKEM_ENCAPS_KEY,
    MLKEM_MSG,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_SHARED_KEY,
    MLKEM_STATUS,
)
from seq_lib.sep_sw_reset_seq import SepSwReset

TEST = "sep_abr_combined_cmd_kat_test"
CHK = "ABR-KEYGEN-DECAPS-SELFCONSIST"
CHK_REJECT = "ABR-KEYGEN-DECAPS-REJECT"

# MLDSA_CTRL.CTRL 100 = KEYGEN+SIGN (abr_reg.rdl), parsed from the RDL text.
CMD_KEYGEN_SIGN = abr_ctrl_cmd("MLDSA_CTRL", "KEYGEN_SIGN")

# Outer limits of the bounded waits (environment choice, logged as bound=).
# Same limits as sep_abr_command_matrix_rand_test, which runs the same commands.
VALID_POLLS = 8_000
VALID_GAP = 200
READY_POLLS = 4_000
READY_GAP = 20


def _hex(words: list[int]) -> str:
    return "".join(f"{w:08x}" for w in words)


def _match_count(got: list[int], exp: list[int]) -> int:
    return sum(1 for g, e in zip(got, exp) if g == e)


def _words_to_bytes(words: list[int]) -> bytes:
    """ABR I/O byte order: byte b sits in word b // 4, bits (b % 4) * 8 (little-endian)."""
    return b"".join(w.to_bytes(4, "little") for w in words)


def implicit_reject_key(z_words: list[int], c_words: list[int]) -> list[int]:
    """FIPS 203 ML-KEM.Decaps_internal implicit-rejection key K_bar = J(z || c).

    J(s) = SHAKE256(s, 8 * 32) (FIPS 203, section 4.1). Returned as 8 ABR words.
    """
    k = hashlib.shake_256(_words_to_bytes(z_words) + _words_to_bytes(c_words)).digest(32)
    return [int.from_bytes(k[i : i + 4], "little") for i in range(0, 32, 4)]


class _Timeout(Exception):
    """A bounded wait of the ML-KEM chain expired."""


@pyuvm.test()
class sep_abr_combined_cmd_kat_test(sep_base_test):
    """ML-KEM KEYGEN+DECAPS self-consistency against a single-step ENCAPS; key windows logged."""

    required_evidence = (f"CHK-{CHK}", f"CHK-{CHK_REJECT}")

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check through SepChkLog and remember that it ran."""
        self._graded.add(name)
        return self.chk.ok(name, cond, **fields)

    # --- register access ----------------------------------------------------
    async def _poll(self, status: int, mask: int, polls: int, gap: int) -> int | None:
        """First STATUS read with a bit of ``mask`` set; None when the bound expires."""
        for _ in range(polls):
            st = await self.abr.rd32(status)
            if st & mask:
                return st
            await ClockCycles(cocotb.top.clk_i, gap)
        return None

    async def _kem_ready(self, where: str) -> int:
        st = await self._poll(MLKEM_STATUS, KEM_ST_READY, READY_POLLS, READY_GAP)
        if st is None:
            raise _Timeout(f"{where}: READY bound={READY_POLLS}x{READY_GAP}")
        return st

    async def _kem_command(self, inputs, cmd: int, where: str, pre_read=None) -> int:
        """READY wait, VALID-pre control, input writes, command write, VALID wait.

        ``pre_read`` runs after the input writes and before the command write.
        Returns STATUS at the first read with VALID or ERROR set.
        """
        st_pre = await self._kem_ready(f"{where} pre-command")
        self.chk.ctrl(
            "ABR-VALID-PRE",
            not st_pre & KEM_ST_VALID,
            cmd=where,
            valid=int(bool(st_pre & KEM_ST_VALID)),
            ready=int(bool(st_pre & KEM_ST_READY)),
        )
        for addr, words in inputs:
            await self.abr.write_words(addr, list(words))
        if pre_read is not None:
            await pre_read()
        await self.abr.wr32(MLKEM_CTRL, cmd)
        st = await self._poll(MLKEM_STATUS, KEM_ST_VALID | KEM_ST_ERROR, VALID_POLLS, VALID_GAP)
        if st is None:
            raise _Timeout(f"{where}: VALID bound={VALID_POLLS}x{VALID_GAP}")
        return st

    async def _kem_zeroize(self, where: str) -> None:
        await self.abr.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._kem_ready(f"{where} post-zeroize")

    async def _abr_reset(self) -> None:
        """ABR software reset: SW_RESET_N bit 6 low, then high."""
        await self.swrst.park("abr")
        await self.swrst.release("abr")

    async def _recover(self, where: str) -> None:
        """Clean-up after a timed-out wait: ABR reset, bounded READY wait on both blocks."""
        self.logger.info("ABR-RECOVER seed=%d where=%s", self.seed, where)
        await self._abr_reset()
        for status, ready in ((MLKEM_STATUS, KEM_ST_READY), (ABR_STATUS, ST_READY)):
            if await self._poll(status, ready, READY_POLLS, READY_GAP) is None:
                raise AssertionError(
                    f"ABR READY did not return within {READY_POLLS}x{READY_GAP} clocks "
                    f"after the recovery reset ({where})"
                )

    # --- ML-KEM chain -------------------------------------------------------
    async def _kem_chain(self) -> None:
        # Step 1: single-step ENCAPS against the ACVP keyGen ek. Stimulus only.
        st = await self._kem_command(
            [(MLKEM_ENCAPS_KEY, NIST_KEM_KG_EK), (MLKEM_MSG, NIST_KEM_ENC_M)],
            KEM_CMD_ENCAPS,
            "encaps",
        )
        if not st & KEM_ST_VALID:
            self._grade(
                CHK, False, step="encaps", reason="error_without_valid", status=f"0x{st:08x}"
            )
            await self._recover("encaps")
            return
        ct = await self.abr.read_words(MLKEM_CIPHERTEXT, KEM_CT_WORDS)
        k_enc = await self.abr.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        self.chk.obs(
            "ABR-ENCAPS-STIMULUS",
            ek="acvp_keygen",
            m="acvp_encaps",
            obs_error=int(bool(st & KEM_ST_ERROR)),
            ct_words=len(ct),
            ct_w0=f"0x{ct[0]:08x}",
            k=_hex(k_enc),
        )
        k_live = self.chk.ctrl(
            "ABR-ENCAPS-K-NONZERO", any(k_enc), k=_hex(k_enc), k_words=len(k_enc)
        )

        # Step 2: re-arm. ZEROIZE gives READY; the ABR reset then clears any
        # internal state, so K cannot reach KEYGEN+DECAPS other than through c.
        await self._kem_zeroize("after encaps")
        await self._abr_reset()

        # Step 3: KEYGEN+DECAPS with the ACVP seeds and the ciphertext of step 1.
        pre: dict[str, list[int]] = {}

        async def _pre_read() -> None:
            pre["k"] = await self.abr.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)

        st = await self._kem_command(
            [(MLKEM_SEED_D, NIST_KEM_KG_D), (MLKEM_SEED_Z, NIST_KEM_KG_Z), (MLKEM_CIPHERTEXT, ct)],
            KEM_CMD_KEYGEN_DECAPS,
            "keygen_decaps",
            pre_read=_pre_read,
        )
        self.chk.ctrl(
            "ABR-SHARED-KEY-PRE",
            pre["k"] != k_enc,
            pre_zero=int(not any(pre["k"])),
            pre=_hex(pre["k"]),
        )
        if not st & KEM_ST_VALID:
            self._grade(
                CHK, False, step="keygen_decaps", reason="error_without_valid", status=f"0x{st:08x}"
            )
            await self._recover("keygen_decaps")
            return
        k_kd = await self.abr.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        bad = next((i for i, (g, e) in enumerate(zip(k_kd, k_enc)) if g != e), None)
        self._grade(
            CHK,
            len(k_kd) == len(k_enc) == KEM_K_WORDS and bad is None and k_live,
            compare="self_consistency_not_golden",
            words=len(k_kd),
            first_diff_word=bad if bad is not None else "none",
            ss=_hex(k_kd),
            k_encaps=_hex(k_enc),
            valid=int(bool(st & KEM_ST_VALID)),
            obs_error=int(bool(st & KEM_ST_ERROR)),
        )

        # Step 4: key windows after KEYGEN+DECAPS, logged only.
        ek = await self.abr.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        dk = await self.abr.read_words(MLKEM_DECAPS_KEY, KEM_DK_WORDS)
        self.chk.obs(
            "ABR-KEYGEN-DECAPS-KEY",
            ek_match=f"{_match_count(ek, NIST_KEM_KG_EK)}/{KEM_EK_WORDS}",
            dk_match=f"{_match_count(dk, NIST_KEM_KG_DK)}/{KEM_DK_WORDS}",
            ek_nonzero=int(any(ek)),
            dk_nonzero=int(any(dk)),
        )
        await self._kem_zeroize("after keygen_decaps")
        await self._abr_reset()
        await self._kem_reject(ct, k_enc)

    async def _kem_reject(self, ct: list[int], k_enc: list[int]) -> None:
        """KEYGEN+DECAPS on a seed d with one bit flipped: the implicit-rejection key.

        The key pair of d' does not match the ek that produced c, so the
        re-encryption check of ML-KEM.Decaps_internal fails and the result is
        K_bar = J(z || c) (FIPS 203). This grades the keyGen half of the combined
        command against a computed standard value, and shows that the shared-key
        window depends on the written seed.
        """
        d_flip = [NIST_KEM_KG_D[0] ^ 1, *NIST_KEM_KG_D[1:]]
        exp = implicit_reject_key(NIST_KEM_KG_Z, ct)
        st = await self._kem_command(
            [(MLKEM_SEED_D, d_flip), (MLKEM_SEED_Z, NIST_KEM_KG_Z), (MLKEM_CIPHERTEXT, ct)],
            KEM_CMD_KEYGEN_DECAPS,
            "keygen_decaps_reject",
        )
        if not st & KEM_ST_VALID:
            self._grade(
                CHK_REJECT,
                False,
                step="keygen_decaps_reject",
                reason="error_without_valid",
                status=f"0x{st:08x}",
            )
            await self._recover("keygen_decaps_reject")
            return
        got = await self.abr.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        bad = next((i for i, (g, e) in enumerate(zip(got, exp)) if g != e), None)
        self._grade(
            CHK_REJECT,
            len(got) == KEM_K_WORDS and bad is None,
            d_flip="word0_bit0",
            first_diff_word=bad if bad is not None else "none",
            ss=_hex(got),
            exp=_hex(exp),
            ne_k_encaps=int(exp != k_enc),
            obs_error=int(bool(st & KEM_ST_ERROR)),
        )
        await self._kem_zeroize("after keygen_decaps_reject")

    # --- ML-DSA observation -------------------------------------------------
    async def _dsa_keygen_sign(self) -> None:
        """One KEYGEN+SIGN with the inputs of the sep_abr_command_matrix_rand_test cell; logged."""
        st_pre = await self._poll(ABR_STATUS, ST_READY, READY_POLLS, READY_GAP)
        if st_pre is None:
            self.chk.obs("ABR-KEYGEN-SIGN-KEY", pk_match="n/a", reason="ready_timeout")
            await self._recover("keygen_sign/ready")
            return
        await self.abr.write_words(ABR_SEED, list(NIST_KG_SEED))
        await self.abr.write_words(ABR_EXTERNAL_MU, list(NIST_SG_MU))
        await self.abr.write_words(ABR_ENTROPY, list(self.cfg.entropy))
        await self.abr.wr32(ABR_CTRL, CMD_KEYGEN_SIGN | CTRL_EXTERNAL_MU)
        st = await self._poll(ABR_STATUS, ST_VALID | ST_ERROR, VALID_POLLS, VALID_GAP)
        if st is None:
            self.chk.obs("ABR-KEYGEN-SIGN-KEY", pk_match="n/a", reason="valid_timeout")
            await self._recover("keygen_sign/valid")
            return
        pk = await self.abr.read_words(ABR_PUBKEY, PK_WORDS)
        self.chk.obs(
            "ABR-KEYGEN-SIGN-KEY",
            pk_match=f"{_match_count(pk, NIST_KG_PK)}/{PK_WORDS}",
            pk_nonzero=int(any(pk)),
            valid_pre=int(bool(st_pre & ST_VALID)),
            valid=int(bool(st & ST_VALID)),
            obs_error=int(bool(st & ST_ERROR)),
        )
        await self.abr.wr32(ABR_CTRL, CTRL_ZEROIZE)
        if await self._poll(ABR_STATUS, ST_READY, READY_POLLS, READY_GAP) is None:
            await self._recover("keygen_sign/zeroize")

    # --- scenario -----------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.cfg = SepAbrKeygenCfg(self.seed)
        self.chk = SepChkLog(self, TEST, self.seed)
        self._graded: set[str] = set()

        # KMAC, AES, HMAC and OTBN parked; ABR (bit 6) released.
        await self.bring_up_no_cpu(park=("otbn", "aes", "hmac", "kmac"))
        if getattr(self, "swrst", None) is None:
            self.swrst = SepSwReset(self)
        await self.swrst.release("abr")
        base = await self.swrst.read_back()
        self.logger.info("SW_RESET_N baseline seed=%d value=0x%08x", self.seed, base)
        self.logger.info(
            "PLAN seed=%d kem_keygen=acvp encaps_m=acvp dsa_seed=acvp entropy[0]=0x%08x",
            self.seed,
            self.cfg.entropy[0],
        )
        self.abr = SepAbr(self)

        try:
            await self._kem_chain()
        except _Timeout as exc:
            for name in (CHK, CHK_REJECT):
                if name not in self._graded:
                    self._grade(name, False, reason="timeout", detail=str(exc))
            await self._recover("kem_chain")

        await self._dsa_keygen_sign()
        self.chk.finish()
