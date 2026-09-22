# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One decryption INPUT is wrong; the payload decrypts to garbage and is refused.

Three rows share this base, one per input the ROM's payload key and cipher depend
on (``manifest_crypto.c``, ``decrypt_payload``):

  * the ``CLASS_KEY`` fuse -- the KBKDF root, read from OTP;
  * the manifest's ``encryption_kdf_input`` -- the info/salt pair the KBKDF runs
    over;
  * the manifest's ``encryption_iv`` -- the CBC initialisation vector.

WHY NONE OF THE THREE PRODUCES A DECRYPTION ERROR. AES-CBC decryption is a
permutation and the ROM's ``aes128cbc_decrypt`` reports a failure only on a bad
length or a hardware alert (``aes_driver.c``). A wrong key or a wrong IV therefore
decrypts "successfully" to garbage, ``DECRYPT_OK`` is printed, and the boot fails
one arm later where ``validate_manifest_payload`` reads the recovered TOC header
and finds it is not ``PTOC`` (``manifest_load.c``,
``MANIFEST_ERR_BAD_TOC_ID``). Every row is graded on that sequence, because the
error code alone is also what a run that stopped BEFORE decryption would reach.

THE FALSE PASS EACH ROW IS BUILT TO AVOID, and the two checks that close it:

  * a run in which decryption never happened. ``CHK-DECRYPT-ARM`` requires
    ``PLD_HASH_OK`` then ``DECRYPT_START`` then ``DECRYPT_OK`` inside the
    primary's own slot attempt, with the rejection strictly after them;
  * a run in which something OTHER than the named input was wrong. The stimulus
    oracle below decrypts the shipped ciphertext twice offline: once with the
    golden key and IV, which must yield ``PTOC``, and once with the inputs THIS
    row hands the ROM, which must not. The first says the ciphertext and every
    other encryption field are the golden image's; the second says the named
    input alone is enough to break the TOC identifier.

THE BACKUP IS THE IN-RUN CONTROL. A primary refused on its TOC identifier is a
warning, not a terminal failure: the slot loop takes the backup and the boot
completes (``sep_primary_fail_backup_boot_base``). For the IV and KDF-input rows
the backup is encrypted and golden, so one run shows the SAME fuse, the SAME AES
engine and the SAME ROM decrypting correctly -- the difference between the two
slots is one manifest field and nothing else.

THE CLASS-KEY ROW CANNOT HAVE THAT CONTROL, because the fuse is not per-slot: a
wrong ``CLASS_KEY`` breaks every encrypted slot at once. Its image is therefore
packed with an UNENCRYPTED backup (``invalid_class_key.bin``), so the fuse refuses
the primary only and the boot still has a slot to recover from. That row requires
the decryption markers ONCE rather than twice, which is also what separates it
from the other two.

Each row keeps a healthy recovery slot and ends in a completed boot, so none of
them speaks to whether an undecryptable payload must END the boot -- the
requirement ``sep_decryption_failure_terminal_test`` owns.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from env import sep_aes128cbc as aes
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_BUILD_DIR = _SEP_ROOT / "bootrom" / "prod" / "build"
_EFUSE_DIR = (Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
              / "efuse_configurations")

# manifest.h -- the two encryption inputs the manifest carries. Each field is 32
# bytes wide; the IV's upper 16 are zero padding the packer appends and the ROM
# never reads, so only the low 16 are the IV.
OFF_ENCRYPTION_IV = 96
OFF_ENCRYPTION_KDF_INPUT = 128
IV_BYTES = 16
KDF_INPUT_BYTES = 32

# configs/encrypted_boot_test.yaml, which every one of the three images is derived
# from. GOLDEN_CLASS_KEY is its encryption_key_input, i.e. what the CLASS_KEY fuse
# must hold for the ROM to derive the key the payload was encrypted with.
GOLDEN_KDF_INPUT = bytes.fromhex(
    "ffeeddccbbaa99887766554433221100c0c1c2c3c4c5c6c7c8c9cacbcccdcecf")
GOLDEN_CLASS_KEY = bytes.fromhex(
    "9BA9BD532A50BD4DA008B20E1D1FE05400000000000000000000000000000000")
# sep_efuse_lc_prod_bad_class_key.toml -- what an unprogrammed fuse reads.
BAD_CLASS_KEY = bytes(32)

# manifest_crypto.c: FUSE_KEY_LENGTH and AES_KEY_SIZE_BYTES.
CLASS_KEY_BYTES = 32
AES_KEY_BYTES = 16


def kbkdf_hmac_sha256(class_key: bytes, kdf_input: bytes,
                      out_bytes: int = AES_KEY_BYTES) -> bytes:
    """The ROM's payload-key derivation, so a test can predict the key it will use.

    NIST SP 800-108r1 counter mode with one round, HMAC-SHA256 as the PRF, over
    ``counter(4,BE) || info(16) || 0x00 || salt(16) || key_bits(4,BE)``. The ROM
    splits the manifest's 32-byte ``encryption_kdf_input`` into info and salt
    (``manifest_crypto.c``); ``pack_images.py`` splits it the same way.
    """
    if len(kdf_input) != KDF_INPUT_BYTES:
        raise ValueError(f"KDF input must be {KDF_INPUT_BYTES} bytes, got {len(kdf_input)}")
    half = KDF_INPUT_BYTES // 2
    msg = ((1).to_bytes(4, "big") + kdf_input[:half] + b"\x00"
           + kdf_input[half:] + (out_bytes * 8).to_bytes(4, "big"))
    return hmac.new(class_key, msg, hashlib.sha256).digest()[:out_bytes]


def _self_test() -> None:
    """Anchor the derivation on the packer's published key before trusting it.

    Every row argues "the ROM derives a DIFFERENT key from this input". That
    conclusion is worthless if this function does not compute what the ROM
    computes, and a silently wrong KDF here would make all three rows look correct
    for the wrong reason.
    """
    got = kbkdf_hmac_sha256(GOLDEN_CLASS_KEY, GOLDEN_KDF_INPUT)
    if got != pm.ENC_DERIVED_KEY:
        raise AssertionError(
            f"KBKDF produced {got.hex()} from the golden class key and KDF input, "
            f"but configs/encrypted_boot_test.yaml's encryption_derived_key is "
            f"{pm.ENC_DERIVED_KEY.hex()}; this module cannot predict the ROM's key"
        )


_self_test()


# Which image, which fuse, and which input each row corrupts. ``golden`` names the
# two manifest fields that must still be the golden image's, which is the other
# half of "this input ALONE is wrong".
DEFECTS = {
    "class_key": {
        "image": "invalid_class_key.bin",
        "efuse": "sep_efuse_lc_prod_bad_class_key.toml",
        "class_key": BAD_CLASS_KEY,
        "backup_encrypted": False,
        "what": "the CLASS_KEY fuse the KBKDF derives the payload key from",
    },
    "iv": {
        "image": "invalid_encryption_iv.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "what": "the primary manifest's encryption_iv",
    },
    "kdf_input": {
        "image": "invalid_kdf_input.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "what": "the primary manifest's encryption_kdf_input",
    },
}

# The boot the backup completes, so a row cannot pass on an early exit that
# happened not to fail.
_BOOT_COMPLETED = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")

# Verdicts that would mean the run stopped somewhere other than the TOC
# identifier. DECRYPT_TERMINAL= and the AES/KDF failure tokens would mean the
# injected input stopped the ENGINE, which is a different requirement and the one
# sep_decryption_failure_terminal_test is about. The MANIFEST_ERR= codes are the
# ones the neighbouring arms of this slot attempt can reach, not every code in
# manifest.h; what pins the verdict to the TOC identifier is the positional
# count == 1 assertion on it plus the forbidden CRYPTO_FAIL=.
_OTHER_ERRORS = (td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION, td.ERR_BAD_LENGTH,
                 td.ERR_BAD_TOC_VERSION, td.ERR_PAYLOAD_TOO_LARGE,
                 td.ERR_NO_BL1_IMAGE, td.ERR_TOC_COUNT,
                 0x0003_000C,   # MANIFEST_ERR_SIG_FAILED
                 0x0003_0014,   # MANIFEST_ERR_VERSION_ROLLBACK
                 0x0003_0017,   # MANIFEST_ERR_PAYLOAD_HASH_MISMATCH
                 0x0003_0018)   # MANIFEST_ERR_DECRYPT_FAILED
_FORBIDDEN = (("DECRYPT_TERMINAL=", "CRYPTO_FAIL=", "PLD_HASH_TIMEOUT")
              + td.DECRYPT_FAILURE_TOKENS
              + td.OTHER_PAYLOAD_TOKENS
              + tuple(f"MANIFEST_ERR=0x{code:08x}" for code in _OTHER_ERRORS))


class sep_decrypt_input_defect_base(sep_primary_fail_backup_boot_base):
    """Hand the ROM one wrong decryption input; require garbage, then a failover."""

    # --- member contract ---------------------------------------------------
    # One key of DEFECTS.
    defect: str = ""

    # manifest.h -- the identifier arm, reached only once a plaintext exists.
    primary_expected_error = pm.MANIFEST_ERR_BAD_TOC_ID
    # The arm prints no token of its own, so the error code carries the whole
    # ROM-side statement about which check refused the slot.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; the TOC
    # identifier is checked downstream of both.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.defect in DEFECTS, (
            f"{cls.__name__} must declare defect as one of {list(DEFECTS)}, "
            f"got {cls.defect!r}"
        )
        spec = DEFECTS[cls.defect]
        cls.flash_image = str(_BUILD_DIR / spec["image"])
        cls.efuse_preload = _EFUSE_DIR / spec["efuse"]
        # An encrypted backup's TOC is ciphertext offline, so verify_sealed's TOC
        # arm has nothing to parse; the manifest-side checks still run.
        cls.backup_sealed_check_toc = not spec["backup_encrypted"]
        cls.extra_required = _BOOT_COMPLETED + (td.DECRYPT_START, td.DECRYPT_OK)
        cls.extra_forbidden = _FORBIDDEN

    @property
    def _spec(self) -> dict:
        return DEFECTS[self.defect]

    @property
    def _decrypt_count(self) -> int:
        """Slots that decrypt in this run: the primary, plus the backup when encrypted."""
        return 2 if self._spec["backup_encrypted"] else 1

    # --- stimulus ----------------------------------------------------------
    def corrupt_primary(self, buf: bytearray) -> None:
        """Nothing to plant here.

        The defect is packed into the image by the build (``Makefile``,
        ``decrypt_negative_images``) or burned into the OTP preload, so the primary
        is a genuine packer output with a genuine signature rather than a mutated
        one. :meth:`mutate_flash_image` proves it carries the defect this row names.
        """

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        base = mm.slot_base("primary")
        self._packed_iv = bytes(buf[base + OFF_ENCRYPTION_IV:
                                    base + OFF_ENCRYPTION_IV + IV_BYTES])
        self._packed_kdf = bytes(buf[base + OFF_ENCRYPTION_KDF_INPUT:
                                     base + OFF_ENCRYPTION_KDF_INPUT + KDF_INPUT_BYTES])

        # CHK-STIMULUS-FLAGS: the image this row loaded is the one it is about. The
        # primary must be encrypted or decrypt_payload() is never called, and the
        # backup's state decides how many times decryption must appear.
        assert pm.is_encrypted(buf, "primary"), (
            f"primary payload has encrypted_payload clear in {self.flash_image}: "
            f"the ROM would not call decrypt_payload(), so nothing about decryption "
            f"is being tested"
        )
        want_backup = self._spec["backup_encrypted"]
        got_backup = pm.is_encrypted(buf, "backup")
        assert got_backup == want_backup, (
            f"backup payload encrypted_payload is {int(got_backup)} but this row "
            f"needs {int(want_backup)}; {self.flash_image} is not the image this "
            f"row is about"
        )

        # CHK-STIMULUS-FIELD: exactly one of the three inputs differs from the
        # golden image's, and it is the one this row names.
        iv_golden = self._packed_iv == pm.ENC_IV
        kdf_golden = self._packed_kdf == GOLDEN_KDF_INPUT
        expect_iv_golden = self.defect != "iv"
        expect_kdf_golden = self.defect != "kdf_input"
        assert iv_golden == expect_iv_golden, (
            f"primary manifest IV is {self._packed_iv.hex()} (golden "
            f"{pm.ENC_IV.hex()}); this row needs it {'golden' if expect_iv_golden else 'different'}"
        )
        assert kdf_golden == expect_kdf_golden, (
            f"primary manifest KDF input is {self._packed_kdf.hex()} (golden "
            f"{GOLDEN_KDF_INPUT.hex()}); this row needs it "
            f"{'golden' if expect_kdf_golden else 'different'}"
        )

        # CHK-STIMULUS-CIPHERTEXT: the shipped payload is the GOLDEN image's
        # ciphertext -- decrypting it with the golden key and IV yields the TOC and
        # re-encrypts back to the shipped bytes. Without this, "the ROM recovered
        # garbage" could be a corrupted payload rather than a wrong input.
        p = pm.payload_base(buf, "primary")
        ciphertext = pm.read_bytes(buf, p, pm.payload_hashed_length(buf, "primary"))
        golden_plain = aes.verify_roundtrip(pm.ENC_DERIVED_KEY, pm.ENC_IV, ciphertext)
        assert golden_plain[:len(pm.TOC_MAGIC)] == pm.TOC_MAGIC, (
            f"decrypting the primary payload with the golden key and IV yields "
            f"{golden_plain[:4]!r}, not {pm.TOC_MAGIC!r}: the ciphertext itself is "
            f"wrong, so a rejected TOC would not be attributable to this row's input"
        )

        # CHK-STIMULUS-DERIVED: the inputs this row actually hands the ROM produce
        # a plaintext whose TOC identifier is NOT PTOC. This is the whole claim,
        # established on the artefact before the simulation is trusted with it.
        rom_key = kbkdf_hmac_sha256(self._spec["class_key"], self._packed_kdf)
        rom_plain = aes.decrypt_raw(rom_key, self._packed_iv, ciphertext[:aes.BLOCK_BYTES])
        assert rom_plain[:len(pm.TOC_MAGIC)] != pm.TOC_MAGIC, (
            f"the ROM's own inputs recover {pm.TOC_MAGIC!r} from the primary "
            f"payload, so {self._spec['what']} is not wrong enough to be rejected "
            f"and this row would pass on a boot that worked"
        )

        # The primary is not mutated here, so its seal is the packer's. Checking it
        # anyway is what says the run reaches the TOC arm at all: a stale hash or
        # signature would be refused upstream of decryption.
        pm.verify_sealed(buf, "primary", check_toc=False)
        mm.verify_public_key(buf, "primary")

        self.logger.info(
            "CHK-STIMULUS-FIELD: %s is wrong; primary manifest IV=%s (golden=%s), "
            "KDF input=%s (golden=%s), class key golden=%s",
            self._spec["what"], self._packed_iv.hex(), iv_golden,
            self._packed_kdf.hex(), kdf_golden,
            self._spec["class_key"] == GOLDEN_CLASS_KEY,
        )
        self.logger.info(
            "CHK-STIMULUS-DERIVED: golden key %s + golden IV recovers %r; the ROM's "
            "key %s + IV %s recovers %s -- decryption succeeds and produces garbage",
            pm.ENC_DERIVED_KEY.hex(), pm.TOC_MAGIC, rom_key.hex(),
            self._packed_iv.hex(), rom_plain[:4].hex(),
        )
        self.logger.info(
            "CHK-STIMULUS-SEALED: primary passes payload_hash over its ciphertext, "
            "manifest_hash over the TBS and RSA verification against the dev0 "
            "modulus, and carries the ROM's slot-0 key -- the seal is the packer's, "
            "not a re-seal"
        )
        return super().mutate_flash_image(buf)

    def check_efuse(self, image) -> None:
        """The OTP half of "this input alone is wrong"."""
        fd.assert_clean_key_fuses(image)
        want = int.from_bytes(self._spec["class_key"], "little")
        got = image.field_int("CLASS_KEY")
        assert got == want, (
            f"OTP CLASS_KEY is 0x{got:064x}, expected 0x{want:064x} "
            f"({self._spec['efuse']}). The ROM derives its payload key from this "
            f"fuse, so a value this row did not choose decides the run"
        )
        golden = int.from_bytes(GOLDEN_CLASS_KEY, "little")
        if self.defect == "class_key":
            assert got != golden, (
                "OTP CLASS_KEY is the key the payload was encrypted under, so the "
                "payload would decrypt correctly and this row would test nothing"
            )
        else:
            assert got == golden, (
                f"OTP CLASS_KEY is 0x{got:064x}, not the packing key "
                f"0x{golden:064x}: the key would be wrong as well as "
                f"{self._spec['what']}, and the rejection would not be attributable"
            )
        self.logger.info(
            "CHK-STIMULUS-CLASS-KEY: OTP CLASS_KEY=0x%064x, packing key=0x%064x, "
            "equal=%s", got, golden, got == golden,
        )

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_err = fd.assert_slot_attributed(console, slot_err,
                                          after=i_psrc, before=i_bsrc)

        # CHK-DECRYPT-ARM: the primary authenticated its ciphertext, drove the AES
        # engine to completion, and only THEN was refused. Without the ordering the
        # error code is equally satisfied by a run that never decrypted anything.
        want = self._decrypt_count
        for marker in (td.DECRYPT_START, td.DECRYPT_OK):
            n = fd.count(console, marker)
            assert n == want, (
                f"{marker} appeared {n} times, expected exactly {want} "
                f"({'primary and recovering backup' if want == 2 else 'the primary only; this row backs up onto a plaintext slot'}). "
                f"Console: {console}"
            )
        i_hash = fd.first_index(console, "PLD_HASH_OK")
        i_start = fd.first_index(console, td.DECRYPT_START)
        i_ok = fd.first_index(console, td.DECRYPT_OK)
        assert i_psrc < i_hash < i_start < i_ok < i_err, (
            f"expected primary read@{i_psrc} -> PLD_HASH_OK@{i_hash} -> "
            f"{td.DECRYPT_START}@{i_start} -> {td.DECRYPT_OK}@{i_ok} -> "
            f"{slot_err}@{i_err}: the payload hash covers ciphertext and must be "
            f"verified before decryption, and the TOC refused after it. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-DECRYPT-ARM: primary@%d -> PLD_HASH_OK@%d -> %s@%d -> %s@%d -> "
            "%s@%d, and the decryption markers appear %d time(s)",
            i_psrc, i_hash, td.DECRYPT_START, i_start, td.DECRYPT_OK, i_ok,
            slot_err, i_err, want,
        )

        # CHK-BACKUP-DECRYPTED: the in-run control. The recovering slot is
        # encrypted with the same fuse and the same engine and differs from the
        # primary in one manifest field, so its successful decryption is positive
        # evidence that the field is what refused the primary.
        if self._spec["backup_encrypted"]:
            i_bstart = fd.first_index(console, td.DECRYPT_START, after=i_bsrc)
            i_bok = fd.first_index(console, td.DECRYPT_OK, after=i_bsrc)
            i_mok = fd.first_index(console, "MANIFEST_OK")
            assert i_bsrc < i_bstart < i_bok < i_mok, (
                f"expected backup read@{i_bsrc} -> {td.DECRYPT_START}@{i_bstart} -> "
                f"{td.DECRYPT_OK}@{i_bok} -> MANIFEST_OK@{i_mok}: the recovering "
                f"slot did not decrypt its own payload, so the run does not show "
                f"the same fuse and engine working. Console: {console}"
            )
            self.logger.info(
                "CHK-BACKUP-DECRYPTED: backup@%d -> %s@%d -> %s@%d -> MANIFEST_OK@%d "
                "with the same CLASS_KEY fuse and golden manifest fields",
                i_bsrc, td.DECRYPT_START, i_bstart, td.DECRYPT_OK, i_bok, i_mok,
            )

        # CHK-STIMULUS-SERVED: the device really returned this row's encryption
        # fields. The console cannot separate the three rows -- they share one error
        # code -- and this can.
        fd.assert_served_field(self.logger, flash, "primary", OFF_ENCRYPTION_IV,
                               self._packed_iv, "the primary manifest encryption_iv")
        fd.assert_served_field(self.logger, flash, "primary",
                               OFF_ENCRYPTION_KDF_INPUT, self._packed_kdf,
                               "the primary manifest encryption_kdf_input")

        self.logger.info(
            "CHK-DECRYPT-INPUT-RULE: with %s wrong, the primary decrypted to "
            "garbage and was refused %s@%d inside its own attempt; the backup was "
            "read@%d and booted",
            self._spec["what"], slot_err, i_err, i_bsrc,
        )
