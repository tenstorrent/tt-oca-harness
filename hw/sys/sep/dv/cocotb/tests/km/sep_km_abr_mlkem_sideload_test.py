# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM -> ABR ML-KEM sideload: the three KV lanes the facade serves.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

Adams Bridge pulls its ML-KEM inputs from a Caliptra Key Vault. SEP has no
Caliptra KV: the KM pushes keys into a sideload CSR over its private key bus
and ``sep_abr_kv_shim`` re-presents that CSR on the KV ports. The shim serves
three read lanes and one write lane, and only the ML-DSA lane has a consumer
elsewhere in this suite:

  * kv_read[1] -- ML-KEM seed, 16 dwords, D[0..7] then Z[0..7]. One lane
    carrying two separately-valid blocks, split on read_offset[3].
  * kv_read[2] -- ML-KEM message, 8 dwords.
  * kv_write   -- the encapsulation shared key, written back into the sideload
    CSR and latched with KEY_CTRL.key_valid on the final dword.

Each leg compares a sideloaded run against a direct-register run of the same
words, and each is preceded by a run on *different* words, so the compare
fails both when the sideload delivers nothing (a stale register produces the
earlier value) and when it delivers the wrong block (D and Z swapped, or the
16-dword lane split at the wrong bit).

The encapsulation key depends on D only, and software cannot read Z back, so
the seed leg grades Z at the engine: the read-only probe
``abr_mlkem_seed_z_probe_o`` (SEP_TB_ARCH exception list) must show the REF Z
after the REF keygen and the ALT Z after the sideloaded keygen.

Key Manager word i and register index i carry the same dword
(doc/adams_bridge.adoc, abr-seed-word-order), so each sideloaded run must equal
the direct-register run of the same words in the same order. Every seed and
message has eight pairwise-distinct words, and no word is shared between D and
Z, so a dword reversal, any other word permutation or a D/Z mix-up fails.

The shared key the engine writes back is graded by value: the KM consumes it
into the KPV and transfers it to AES, and the AES ciphertext must equal the
AES-256 golden keyed with the engine's own MLKEM_SHARED_KEY words from the
register-driven ENCAPS of the same inputs. The sideload block's KEY words are
on the KM-private bus, so AES is the consumer that grades them.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_aes_golden import aes256_ecb_encrypt_words
from sep_base_test import sep_base_test
from seq_lib.sep_abr_mlkem_seq import (
    KEM_CMD_ENCAPS,
    KEM_CMD_KEYGEN,
    KEM_CT_WORDS,
    KEM_CTRL_ZEROIZE,
    KEM_EK_WORDS,
    KEM_K_WORDS,
    KEM_MSG_WORDS,
    KEM_SEED_WORDS,
    KEM_ST_ERROR,
    KEM_ST_READY,
    KEM_ST_VALID,
    KV_READ_EN,
    KV_WRITE_EN,
    MLKEM_CIPHERTEXT,
    MLKEM_CTRL,
    MLKEM_ENCAPS_KEY,
    MLKEM_KV_MSG_RD_CTRL,
    MLKEM_KV_SEED_RD_CTRL,
    MLKEM_KV_SK_WR_CTRL,
    MLKEM_MSG,
    MLKEM_NAME0,
    MLKEM_NAME1,
    MLKEM_SEED_D,
    MLKEM_SEED_Z,
    MLKEM_SHARED_KEY,
    MLKEM_STATUS,
    SepAbrMlkem,
)
from seq_lib.sep_aes_seq import SepAes
from seq_lib.sep_km_mailbox_seq import (
    KM_DEST_ABR_MLKEM_MSG,
    KM_DEST_ABR_MLKEM_SEED_D,
    KM_DEST_ABR_MLKEM_SEED_Z,
    KM_DEST_AES,
    KM_RC_FAILURE,
    KM_RC_SUCCESS,
    KM_RESP_ABR_SHARED_KEY_READY,
    SepKmMailbox,
)

# Four directed seed halves. D and Z differ so a swapped pair fails the
# compare; the REF pair differs from the ALT pair so a seed that never arrived
# reproduces the REF public key and fails it too.
_D_ALT = [
    0x0BADC0DE,
    0x13572468,
    0xA5A5A5A5,
    0xFEEDFACE,
    0x2468ACE0,
    0x5A5A0F0F,
    0x97531ECA,
    0x600DF00D,
]
_Z_ALT = [
    0x1234ABCD,
    0x0F0F0F0F,
    0xC0FFEE00,
    0x5EED5EED,
    0x7E57CA5E,
    0x31415926,
    0x4B1D2C3E,
    0x8BADF00D,
]
_D_REF = [
    0x00112233,
    0x44556677,
    0x8899AABB,
    0xCCDDEEFF,
    0x10213243,
    0x54657687,
    0x98A9BACB,
    0xDCEDFE0F,
]
_Z_REF = [
    0xDEADBEEF,
    0x5A5A5A5A,
    0x0102_0304,
    0x7F7F7F7F,
    0x0506_0708,
    0x6B6B6B6B,
    0x090A_0B0C,
    0xCAFED00D,
]

# Two messages for the kv_read[2] lane, same discipline.
_M_ALT = [
    0x0F1E2D3C,
    0x4B5A6978,
    0x8796A5B4,
    0xC3D2E1F0,
    0x1F2E3D4C,
    0x5B6A7988,
    0x97A6B5C4,
    0xD3E2F100,
]
_M_REF = [
    0x11223344,
    0x55667788,
    0x99AABBCC,
    0xDDEEFF00,
    0x21324354,
    0x65768798,
    0xA9BACBDC,
    0xEDFE0F10,
]

for _w in (_D_ALT, _Z_ALT, _D_REF, _Z_REF, _M_ALT, _M_REF):
    assert len(set(_w)) == len(_w), "test construction error: repeated word in a block"
assert not set(_D_ALT) & set(_Z_ALT) and not set(_D_REF) & set(_Z_REF), (
    "test construction error: D and Z share a word"
)

# AES-256 ECB plaintext for the shared-key value check.
_SK_AES_PT = [0x03020100, 0x07060504, 0x0B0A0908, 0x0F0E0D0C]

# The KPV destination the consumed shared key is stored under. AES is also
# the engine that grades the stored words by value (CHK-KEM-SK-VALUE).
_SK_DEST = KM_DEST_AES

_POLL_ITERS = 20000
_POLL_GAP = 200


@pyuvm.test()
class sep_km_abr_mlkem_sideload_test(sep_base_test):
    """ML-KEM seed, message and shared-key transfers across the KV facade."""

    required_evidence = (
        "CHK-KEM-SEED-REF",
        "CHK-KEM-SEED-SIDELOAD",
        "CHK-KEM-MSG-SIDELOAD",
        "CHK-KEM-SK-CONFIDENTIAL",
        "CHK-KEM-SK-NOTIFY",
        "CHK-KEM-SK-WRITEBACK",
        "CHK-KEM-SK-VALUE",
    )

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

    async def _zeroize(self, kem, *, what: str) -> None:
        await kem.wr32(MLKEM_CTRL, KEM_CTRL_ZEROIZE)
        await self._wait_status(kem, KEM_ST_VALID, 0, what=f"{what} post-zeroize VALID clear")
        await self._wait_status(kem, KEM_ST_READY, KEM_ST_READY, what=f"{what} post-zeroize READY")

    async def _keygen(
        self, kem, d: list[int] | None, z: list[int] | None, *, what: str
    ) -> list[int]:
        """KEYGEN and return the encapsulation key. ``d``/``z`` None means the
        seed arrives over the KV lane instead of the register."""
        await self._wait_status(kem, KEM_ST_READY, KEM_ST_READY, what=f"{what} pre-command READY")
        if d is not None:
            await kem.write_words(MLKEM_SEED_D, list(d))
        if z is not None:
            await kem.write_words(MLKEM_SEED_Z, list(z))
        await kem.wr32(MLKEM_CTRL, KEM_CMD_KEYGEN)
        st = await self._wait_status(kem, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID")
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ek = await kem.read_words(MLKEM_ENCAPS_KEY, KEM_EK_WORDS)
        assert any(w != 0 for w in ek), f"{what} FAIL: the encapsulation key is all zero"
        return ek

    async def _encaps(
        self, kem, ek: list[int], msg: list[int] | None, *, what: str
    ) -> tuple[list[int], list[int]]:
        """ENCAPS over ``ek``; returns (ciphertext, shared key as read).

        ``msg`` None means the message arrives over the KV lane instead of the
        register.

        The CIPHERTEXT is what the value compares use: it is public, and a
        deterministic function of the encapsulation key and the message.

        The shared key is returned too. Whether it reads back at all is the
        contract of CHK-KEM-SK-CONFIDENTIAL, and the value read on a fully
        register-driven ENCAPS is the reference for CHK-KEM-SK-VALUE. The
        ML-KEM shared key is consumed directly by the Key Manager
        (doc/crypto.adoc, "a gated ML-KEM shared-key interrupt consumed
        directly by the Key Manager") and
        shared-key storage is secret-bearing Class 2 logic
        (doc/attack_countermeasures.adoc), so a key the vault sourced must not
        be readable by software over the CSR aperture. This test establishes
        that it IS readable when every input came over the bus, and is withheld
        once an input came from the vault.
        """
        await self._wait_status(kem, KEM_ST_READY, KEM_ST_READY, what=f"{what} pre-command READY")
        await kem.write_words(MLKEM_ENCAPS_KEY, list(ek))
        if msg is not None:
            await kem.write_words(MLKEM_MSG, list(msg))
        await kem.wr32(MLKEM_CTRL, KEM_CMD_ENCAPS)
        st = await self._wait_status(kem, KEM_ST_VALID, KEM_ST_VALID, what=f"{what} VALID")
        assert (st & KEM_ST_ERROR) == 0, f"{what}: VALID with ERROR (0x{st:08x})"
        ct = await kem.read_words(MLKEM_CIPHERTEXT, KEM_CT_WORDS)
        assert any(w != 0 for w in ct), f"{what} FAIL: the ciphertext is all zero"
        k = await kem.read_words(MLKEM_SHARED_KEY, KEM_K_WORDS)
        return ct, k

    async def _sideload(self, words: list[int], dest: int, *, what: str) -> None:
        """Push ``words`` into one sideload block over the KM mailbox."""
        handle = await self.km.key_load(key_words=list(words), dest=dest)
        rc, arg = await self.km.key_transfer(handle=handle, dest=dest)
        assert rc == KM_RC_SUCCESS, f"{what} FAIL: CMD_KEY_TRANSFER dest=0x{dest:02x} rc={rc}"
        assert (arg & 0xFF) == handle and ((arg >> 8) & 0xFF) == dest, (
            f"{what} FAIL: RETURN_ARG 0x{arg:08x} does not echo handle 0x{handle:02x} "
            f"dest 0x{dest:02x}"
        )

    def _seed_z_probe(self) -> list[int]:
        """The eight Z words the ABR engine holds, word i at bits [32*i +: 32]."""
        v = self.rd_known(cocotb.top.abr_mlkem_seed_z_probe_o)
        return [(v >> (32 * i)) & 0xFFFF_FFFF for i in range(KEM_SEED_WORDS)]

    @staticmethod
    def _first_mismatch(got: list[int], exp: list[int]) -> int | None:
        return next((i for i, (g, e) in enumerate(zip(got, exp)) if g != e), None)

    def _same(self, got: list[int], exp: list[int], *, chk: str, what: str) -> None:
        assert len(got) == len(exp), (
            f"{chk} FAIL: {what} is {len(got)} words, expected {len(exp)} -- a short "
            "readback would narrow the compare to the overlap"
        )
        bad = self._first_mismatch(got, exp)
        assert bad is None, (
            f"{chk} FAIL: {what} differs at word {bad} of {len(exp)}: "
            f"got=0x{got[bad]:08x} exp=0x{exp[bad]:08x}"
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        kem = SepAbrMlkem(self)
        self.km = SepKmMailbox(self)
        self.aes = SepAes(self)
        await self.bring_up_entropy(strict=True, score_km="observe", score_sinks={"aes": "observe"})
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        # Logged for the record, not graded: abr_reg.rdl declares NAME sw=r
        # with no reset, and no SEP document gives its value. A dead decode
        # reads both reference keys as zero and fails CHK-KEM-SEED-REF.
        name0 = await kem.rd32(MLKEM_NAME0)
        name1 = await kem.rd32(MLKEM_NAME1)
        self.logger.info(
            "ABR ML-KEM identity words (information only): NAME0=0x%08x NAME1=0x%08x",
            name0,
            name1,
        )

        # --- CHK-KEM-SEED-REF: the two reference keygens ----------------------
        ek_alt = await self._keygen(kem, _D_ALT, _Z_ALT, what="CHK-KEM-SEED-REF alt")
        await self._zeroize(kem, what="after alt keygen")
        ek_ref = await self._keygen(kem, _D_REF, _Z_REF, what="CHK-KEM-SEED-REF ref")
        assert ek_alt != ek_ref, (
            "CHK-KEM-SEED-REF FAIL: the two seed pairs produce the same "
            "encapsulation key, so the sideload compare could not tell them apart"
        )
        # The probe follows a register-written Z. This is the positive control
        # for the Z compare below: the probe is live and shows a Z that is not
        # the one the sideload delivers.
        z_ref_eng = self._seed_z_probe()
        self._same(
            z_ref_eng,
            _Z_REF,
            chk="CHK-KEM-SEED-REF",
            what="the engine's Z after the REF register write",
        )
        self.logger.info(
            "CHK-KEM-SEED-REF PASS: the two (D, Z) pairs give distinct %d-word "
            "encapsulation keys (ek_alt[0]=0x%08x ek_ref[0]=0x%08x); the engine Z "
            "probe reads the REF Z z[0]=0x%08x z[3]=0x%08x",
            KEM_EK_WORDS,
            ek_alt[0],
            ek_ref[0],
            z_ref_eng[0],
            z_ref_eng[3],
        )
        await self._zeroize(kem, what="after ref keygen")

        # --- CHK-KEM-SEED-SIDELOAD: kv_read[1], D||Z split at offset[3] -------
        # The Z the engine holds before the KV read. It must not already be
        # the ALT Z, or the Z compare below could not fail.
        z_pre = self._seed_z_probe()
        assert z_pre != _Z_ALT, (
            "CHK-KEM-SEED-SIDELOAD FAIL: the engine already holds the ALT Z before "
            "the KV read, so the Z compare could not detect a lost delivery"
        )
        await self._sideload(_D_ALT, KM_DEST_ABR_MLKEM_SEED_D, what="CHK-KEM-SEED-SIDELOAD")
        await self._sideload(_Z_ALT, KM_DEST_ABR_MLKEM_SEED_Z, what="CHK-KEM-SEED-SIDELOAD")
        await kem.wr32(MLKEM_KV_SEED_RD_CTRL, KV_READ_EN)
        ek_km = await self._keygen(kem, None, None, what="CHK-KEM-SEED-SIDELOAD")
        # KEYGEN does not write Z, so the probe still shows what the KV read
        # delivered.
        z_km = self._seed_z_probe()
        assert ek_km != ek_ref, (
            "CHK-KEM-SEED-SIDELOAD FAIL: the KV read produced the REF "
            "encapsulation key, so the seed registers still held the previous "
            "pair -- a stale seed, not a delivered one"
        )
        self._same(
            ek_km,
            ek_alt,
            chk="CHK-KEM-SEED-SIDELOAD",
            what="the encapsulation key from the KM-sideloaded (D, Z)",
        )
        # Word i of the delivered Z must sit at engine index i.
        self._same(
            z_km,
            _Z_ALT,
            chk="CHK-KEM-SEED-SIDELOAD",
            what="the engine's Z after the KV seed read",
        )
        self.logger.info(
            "CHK-KEM-SEED-SIDELOAD PASS: the 16-dword kv_read[1] lane delivered "
            "D[0..%d] and Z[0..%d] -- the %d-word encapsulation key equals the "
            "direct-register keygen of the same words (ek[0]=0x%08x), and the "
            "engine Z moved from z[0]=0x%08x to the ALT Z z[0]=0x%08x z[3]=0x%08x",
            KEM_SEED_WORDS - 1,
            KEM_SEED_WORDS - 1,
            KEM_EK_WORDS,
            ek_km[0],
            z_pre[0],
            z_km[0],
            z_km[3],
        )
        await self._zeroize(kem, what="after sideload keygen")

        # --- CHK-KEM-MSG-SIDELOAD + CHK-KEM-SK-CONFIDENTIAL ------------------
        # The compares run on the CIPHERTEXT, which is public and a
        # deterministic function of (ek, m). The shared key cannot serve: the
        # engine withholds it from software as soon as an input came from the
        # vault, which is the confidentiality rule the next checker grades.
        #
        # Reference first on the OTHER message, so the register holds _M_REF
        # when the sideload leg runs.
        ct_alt, sk_alt = await self._encaps(kem, ek_alt, _M_ALT, what="CHK-KEM-MSG-REF alt")
        assert any(w != 0 for w in sk_alt), (
            "CHK-KEM-SK-CONFIDENTIAL FAIL: the shared key already reads back as "
            "zero on a fully register-driven ENCAPS, so the withheld-key check "
            "below would pass with the readback broken rather than gated"
        )
        await self._zeroize(kem, what="after alt encaps")
        ct_ref, _ = await self._encaps(kem, ek_alt, _M_REF, what="CHK-KEM-MSG-REF ref")
        assert ct_alt != ct_ref, (
            "CHK-KEM-MSG-SIDELOAD FAIL: the two messages produce the same "
            "ciphertext, so the sideload compare below could not tell them apart"
        )
        await self._zeroize(kem, what="after ref encaps")

        await self._sideload(_M_ALT, KM_DEST_ABR_MLKEM_MSG, what="CHK-KEM-MSG-SIDELOAD")
        await kem.wr32(MLKEM_KV_MSG_RD_CTRL, KV_READ_EN)
        ct_km, sk_km = await self._encaps(kem, ek_alt, None, what="CHK-KEM-MSG-SIDELOAD")
        assert ct_km != ct_ref, (
            "CHK-KEM-MSG-SIDELOAD FAIL: the KV read produced the ciphertext of "
            "the previous message, so MLKEM_MSG still held the earlier value"
        )
        self._same(
            ct_km,
            ct_alt,
            chk="CHK-KEM-MSG-SIDELOAD",
            what="the ciphertext from the KM-sideloaded message",
        )
        self.logger.info(
            "CHK-KEM-MSG-SIDELOAD PASS: the %d-dword message lane delivered the "
            "message -- the %d-word ciphertext equals the direct-register encaps "
            "of the same words",
            KEM_MSG_WORDS,
            KEM_CT_WORDS,
        )

        # Same ENCAPS, and now the shared key must NOT be visible: its message
        # came from the vault. The register-driven ENCAPS above is the positive
        # control that the readback path works at all, so this is a conditional
        # withholding rather than a readback that never worked.
        assert all(w == 0 for w in sk_km), (
            "CHK-KEM-SK-CONFIDENTIAL FAIL: the shared key of an ENCAPS whose "
            "message came from the vault is readable over the bus "
            f"(first non-zero word 0x{next(w for w in sk_km if w != 0):08x}); a "
            "shared key the vault sourced is consumed by the Key Manager and "
            "must not reach software over the CSR aperture"
        )
        self.logger.info(
            "CHK-KEM-SK-CONFIDENTIAL PASS: the shared key reads back on a "
            "register-driven ENCAPS and reads zero once the message came from "
            "the vault, so the withholding is gated and not simply broken"
        )

        # --- CHK-KEM-SK-WRITEBACK: kv_write, and its negative control ---------
        # Nothing has armed the write lane yet, so the sideload block's
        # KEY_VALID is clear and the firmware must refuse to consume.
        rc, _ = await self.km.abr_sk_transfer(dest=_SK_DEST)
        assert rc == KM_RC_FAILURE, (
            f"CHK-KEM-SK-WRITEBACK FAIL: CMD_ABR_SK_TRANSFER returned rc={rc} with "
            "no shared key posted; the accept below would then prove nothing"
        )
        self.logger.info(
            "CHK-KEM-SK-WRITEBACK PASS (refuse): with KEY_VALID clear the shared-key "
            "consume is rejected rc=%d",
            rc,
        )

        await self._zeroize(kem, what="before writeback encaps")
        await kem.wr32(MLKEM_KV_SK_WR_CTRL, KV_WRITE_EN)
        ct_wb, _ = await self._encaps(kem, ek_alt, _M_ALT, what="CHK-KEM-SK-WRITEBACK")
        self._same(
            ct_wb,
            ct_alt,
            chk="CHK-KEM-SK-WRITEBACK",
            what="the ciphertext of the writeback encaps",
        )
        # The firmware announces the posted key before anything asks for it: the
        # shim pulses IRQ_STATUS.key_valid on the final writeback dword, the
        # wrapper gates that onto mlkem_sharedkey_irq_o, and the KM ISR posts an
        # unsolicited frame. This is the only host-side view of that path, and
        # it has to be consumed before the command response can be read.
        notify = await self.km.recv_unsolicited(KM_RESP_ABR_SHARED_KEY_READY)
        self.logger.info(
            "CHK-KEM-SK-NOTIFY PASS: the writeback raised the shared-key "
            "interrupt and the KM posted RESP_ABR_SHARED_KEY_READY (frame=%s)",
            [hex(w) for w in notify],
        )

        rc, arg = await self.km.abr_sk_transfer(dest=_SK_DEST)
        assert rc == KM_RC_SUCCESS, (
            f"CHK-KEM-SK-WRITEBACK FAIL: the engine posted a shared key over "
            f"kv_write but CMD_ABR_SK_TRANSFER returned rc={rc}; either the "
            "writeback never reached the sideload CSR or KEY_VALID was not set"
        )
        assert (arg & 0xFF) != 0, (
            f"CHK-KEM-SK-WRITEBACK FAIL: the consume succeeded with a zero key "
            f"handle (RETURN_ARG 0x{arg:08x})"
        )
        self.logger.info(
            "CHK-KEM-SK-WRITEBACK PASS: the kv_write lane landed the %d-dword shared "
            "key in the sideload CSR and latched KEY_VALID -- the KM consumed it "
            "into KPV handle 0x%02x",
            KEM_K_WORDS,
            arg & 0xFF,
        )

        # --- CHK-KEM-SK-VALUE: the posted words are the engine's shared key ---
        # MLKEM_SHARED_KEY.KEY[i] must hold the engine's own MLKEM_SHARED_KEY
        # word i (doc/adams_bridge.adoc). The writeback ENCAPS ran on the same
        # (ek, m) as the register-driven ENCAPS that read sk_alt back
        # (CHK-KEM-SK-WRITEBACK compared the ciphertexts), so sk_alt is the
        # expected key. The KM moves KEY[0..7] word for word into the KPV
        # handle, and AES encrypts under it.
        sk_handle = arg & 0xFF
        assert sk_alt != sk_alt[::-1], (
            "test construction error: the reference shared key is a dword "
            "palindrome, so the compare below could not detect a reversal"
        )
        golden_sk = aes256_ecb_encrypt_words(list(sk_alt), list(_SK_AES_PT))
        golden_rev = aes256_ecb_encrypt_words(list(sk_alt[::-1]), list(_SK_AES_PT))
        assert golden_sk != golden_rev, (
            "test construction error: the shared key and its dword reversal "
            "encrypt the plaintext identically"
        )
        rc, xarg = await self.km.key_transfer(handle=sk_handle, dest=KM_DEST_AES)
        assert rc == KM_RC_SUCCESS, (
            f"CHK-KEM-SK-VALUE FAIL: CMD_KEY_TRANSFER of shared-key handle "
            f"0x{sk_handle:02x} to AES returned rc={rc}"
        )
        assert (xarg & 0xFF) == sk_handle and ((xarg >> 8) & 0xFF) == KM_DEST_AES, (
            f"CHK-KEM-SK-VALUE FAIL: RETURN_ARG 0x{xarg:08x} does not echo handle "
            f"0x{sk_handle:02x} and dest 0x{KM_DEST_AES:02x}"
        )
        await self.aes.configure_ecb_enc_256(sideload=True)
        await self.aes.trigger_prng_reseed()
        ct_sk = await self.aes.run_ecb_block(list(_SK_AES_PT))
        assert ct_sk == golden_sk, (
            "CHK-KEM-SK-VALUE FAIL: AES under the written-back shared key is not "
            "AES-256 of the engine's MLKEM_SHARED_KEY words"
            + (" (it is the golden of the dword-reversed key)" if ct_sk == golden_rev else "")
            + f":\n  ct     ={[hex(w) for w in ct_sk]}\n"
            f"  golden ={[hex(w) for w in golden_sk]}"
        )
        self.logger.info(
            "CHK-KEM-SK-VALUE PASS: AES-256 under the written-back shared key == golden "
            "keyed with the engine's MLKEM_SHARED_KEY words (ct[0]=0x%08x, "
            "sk[0]=0x%08x sk[7]=0x%08x); the dword-reversed key's golden ct[0]=0x%08x differs",
            ct_sk[0],
            sk_alt[0],
            sk_alt[7],
            golden_rev[0],
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
