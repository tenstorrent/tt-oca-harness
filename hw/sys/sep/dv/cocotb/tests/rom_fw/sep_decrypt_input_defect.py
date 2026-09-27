# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCA AES-256 decryption-input defects with a healthy recovery slot.

The three inputs fail at different current-ROM control points: an erased CLASS_KEY
is refused before KDF, a wrong IV corrupts only the first CBC plaintext block and
therefore reaches the TOC check, and a wrong KDF context normally fails PKCS#7
stripping. Members select one exact packer-produced image through ``defect``.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_BUILD_DIR = _SEP_ROOT / "bootrom" / "prod" / "build"
_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

# OCA-classic manifest fields. The packer's constants remain the authority.
OFF_ENCRYPTION_IV = mm.OFF_ENCRYPTION_IV
OFF_ENCRYPTION_KDF_INPUT = mm.OFF_ENCRYPTION_KDF_INPUT
IV_BYTES = 16
KDF_INPUT_BYTES = 64

# Golden inputs the images were packed with; the CLASS_KEY fuse must hold GOLDEN_CLASS_KEY.
GOLDEN_KDF_INPUT = bytes.fromhex("a5" * 16 + "b6" * 16 + "c7" * 16 + "d8" * 16)
GOLDEN_CLASS_KEY = bytes(range(32))
GOLDEN_IV = bytes(range(0x10, 0x20))
# What an unprogrammed CLASS_KEY fuse reads.
BAD_CLASS_KEY = bytes(32)

CLASS_KEY_BYTES = 32
AES_KEY_BYTES = 32


def kbkdf_hmac_sha256(class_key: bytes, kdf_input: bytes, out_bytes: int = AES_KEY_BYTES) -> bytes:
    """Mirror ``oca_derive_payload_key`` for the AES-256 OCA profile."""
    if len(kdf_input) != KDF_INPUT_BYTES:
        raise ValueError(f"KDF input must be {KDF_INPUT_BYTES} bytes, got {len(kdf_input)}")
    if out_bytes != AES_KEY_BYTES:
        raise ValueError(f"this profile derives a {AES_KEY_BYTES}-byte AES-256 key")
    block = bytearray(192)
    block[:13] = bytes((1, 0, 1, 0, 0, 1, 0x18, 0, 0, 0, 0, 1, 1))
    block[32:43] = b"KM_CLASS_BL"
    block[64:128] = kdf_input
    msg = (1).to_bytes(2, "big") + block + (out_bytes * 8).to_bytes(2, "big")
    return hmac.new(class_key, msg, hashlib.sha256).digest()[:out_bytes]


def _self_test() -> None:
    # Independent KAT for the exact C implementation's AES-256 profile.
    got = kbkdf_hmac_sha256(GOLDEN_CLASS_KEY, GOLDEN_KDF_INPUT)
    expected = bytes.fromhex("da4e1f270faaf863b1ebb284b30e2cc935a10d9e25c5c7e6adc25158b9137292")
    if got != expected:
        raise AssertionError(
            f"KBKDF produced {got.hex()} from the golden class key and KDF input, "
            f"expected {expected.hex()}; this module cannot predict the ROM's key"
        )


_self_test()


DEFECTS = {
    "class_key": {
        "image": "invalid_class_key.bin",
        "efuse": "sep_efuse_lc_prod_bad_class_key.toml",
        "class_key": BAD_CLASS_KEY,
        "backup_encrypted": False,
        "expected_error": mm.boot_err("OCA_FAIL_NO_PROVISIONED_SECRET"),
        "required": ("DECRYPT_CLASS_KEY_EMPTY",),
        "decrypt_starts": 0,
        "decrypt_oks": 0,
        "what": "the CLASS_KEY fuse the KBKDF derives the payload key from",
    },
    "iv": {
        "image": "invalid_encryption_iv.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "expected_error": pm.MANIFEST_ERR_BAD_TOC_ID,
        "required": (td.DECRYPT_START, td.DECRYPT_OK),
        "decrypt_starts": 2,
        "decrypt_oks": 2,
        "what": "the primary manifest's encryption_iv",
    },
    "kdf_input": {
        "image": "invalid_kdf_input.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "expected_error": mm.boot_err("OCA_FAIL_DECRYPT"),
        "required": (td.DECRYPT_START,),
        "decrypt_starts": 2,
        "decrypt_oks": 1,
        "what": "the primary manifest's encryption_kdf_input",
    },
}

# The backup's completed boot, so a row cannot pass on an early exit.
_BOOT_COMPLETED = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")

# Verdicts from unrelated validation arms.
_OTHER_ERRORS = (
    td.ERR_BAD_MAGIC,
    td.ERR_BAD_VERSION,
    td.ERR_BAD_LENGTH,
    td.ERR_BAD_TOC_VERSION,
    td.ERR_PAYLOAD_TOO_LARGE,
    td.ERR_NO_BL1_IMAGE,
    td.ERR_TOC_COUNT,
    0x0003_000C,  # MANIFEST_ERR_SIG_FAILED
    0x0003_0014,  # MANIFEST_ERR_VERSION_ROLLBACK
    0x0003_0017,
)  # MANIFEST_ERR_PAYLOAD_HASH_MISMATCH


class sep_decrypt_input_defect_base(sep_primary_fail_backup_boot_base):
    defect: str = ""

    primary_defect_marker = ""
    # All three defects are downstream of successful signature verification.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.defect in DEFECTS, (
            f"{cls.__name__} must declare defect as one of {list(DEFECTS)}, got {cls.defect!r}"
        )
        spec = DEFECTS[cls.defect]
        cls.flash_image = str(_BUILD_DIR / spec["image"])
        cls.efuse_preload = _EFUSE_DIR / spec["efuse"]
        # An encrypted backup's TOC is ciphertext offline, so skip only the TOC check.
        cls.backup_sealed_check_toc = not spec["backup_encrypted"]
        cls.primary_expected_error = spec["expected_error"]
        cls.extra_required = _BOOT_COMPLETED + spec["required"]
        cls.extra_forbidden = (
            ("CRYPTO_FAIL=", "PLD_HASH_TIMEOUT")
            + td.OTHER_PAYLOAD_TOKENS
            + tuple(
                f"MANIFEST_ERR=0x{code:08x}"
                for code in _OTHER_ERRORS
                if code != spec["expected_error"]
            )
        )

    @property
    def _spec(self) -> dict:
        return DEFECTS[self.defect]

    @property
    def _decrypt_count(self) -> int:
        return 2 if self._spec["backup_encrypted"] else 1

    def corrupt_primary(self, buf: bytearray) -> None:
        # The defect comes from the build or the OTP preload, not from a mutation.
        pass

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        base = mm.slot_base("primary")
        self._packed_iv = bytes(buf[base + OFF_ENCRYPTION_IV : base + OFF_ENCRYPTION_IV + IV_BYTES])
        self._packed_kdf = bytes(
            buf[base + OFF_ENCRYPTION_KDF_INPUT : base + OFF_ENCRYPTION_KDF_INPUT + KDF_INPUT_BYTES]
        )

        # The primary must be encrypted; the backup's encryption sets the decrypt count.
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

        # Exactly one input differs from the golden image: the one this row names.
        iv_golden = self._packed_iv == GOLDEN_IV
        kdf_golden = self._packed_kdf == GOLDEN_KDF_INPUT
        expect_iv_golden = self.defect != "iv"
        expect_kdf_golden = self.defect != "kdf_input"
        assert iv_golden == expect_iv_golden, (
            f"primary manifest IV is {self._packed_iv.hex()} (golden "
            f"{GOLDEN_IV.hex()}); this row needs it "
            f"{'golden' if expect_iv_golden else 'different'}"
        )
        assert kdf_golden == expect_kdf_golden, (
            f"primary manifest KDF input is {self._packed_kdf.hex()} (golden "
            f"{GOLDEN_KDF_INPUT.hex()}); this row needs it "
            f"{'golden' if expect_kdf_golden else 'different'}"
        )

        golden_key = kbkdf_hmac_sha256(GOLDEN_CLASS_KEY, GOLDEN_KDF_INPUT)
        if self.defect == "kdf_input":
            rom_key = kbkdf_hmac_sha256(GOLDEN_CLASS_KEY, self._packed_kdf)
            assert rom_key != golden_key, (
                "the defective 64-byte OCA KDF context derived the golden AES-256 "
                "key, so this image would not exercise the KDF-input failure"
            )

        # A stale seal would refuse the primary before decryption.
        pm.verify_sealed(buf, "primary", check_toc=False)
        mm.verify_public_key(buf, "primary")

        self.logger.info(
            "CHK-STIMULUS-FIELD: %s is wrong; primary manifest IV=%s (golden=%s), "
            "KDF input=%s (golden=%s), class key golden=%s",
            self._spec["what"],
            self._packed_iv.hex(),
            iv_golden,
            self._packed_kdf.hex(),
            kdf_golden,
            self._spec["class_key"] == GOLDEN_CLASS_KEY,
        )
        self.logger.info(
            "CHK-STIMULUS-AES256: golden derived key=%s, IV=%s, KDF context bytes=%d; "
            "the selected defect is expected to report 0x%08x",
            golden_key.hex(),
            self._packed_iv.hex(),
            len(self._packed_kdf),
            self.primary_expected_error,
        )
        self.logger.info(
            "CHK-STIMULUS-SEALED: primary passes payload_hash over its ciphertext, "
            "manifest_hash over the signed region and RSA verification against the dev0 "
            "modulus, and carries the ROM's slot-0 key -- the seal is the packer's, "
            "not a re-seal"
        )
        return super().mutate_flash_image(buf)

    def check_efuse(self, image) -> None:
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
            "CHK-STIMULUS-CLASS-KEY: OTP CLASS_KEY=0x%064x, packing key=0x%064x, equal=%s",
            got,
            golden,
            got == golden,
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

        # CHK-DECRYPT-ARM: each defect reaches a distinct OCA decryption stage.
        for marker, want in (
            (td.DECRYPT_START, self._spec["decrypt_starts"]),
            (td.DECRYPT_OK, self._spec["decrypt_oks"]),
        ):
            n = fd.count(console, marker)
            assert n == want, (
                f"{marker} appeared {n} times, expected exactly {want} "
                f"for the {self.defect} OCA AES-256 scenario. "
                f"Console: {console}"
            )
        i_hash = fd.first_index(console, "PLD_HASH_OK")
        if self.defect == "class_key":
            i_empty = fd.first_index(console, "DECRYPT_CLASS_KEY_EMPTY")
            assert i_psrc < i_hash < i_empty < i_err, (
                f"expected primary read@{i_psrc} -> PLD_HASH_OK@{i_hash} -> "
                f"DECRYPT_CLASS_KEY_EMPTY@{i_empty} -> {slot_err}@{i_err}. "
                f"Console: {console}"
            )
        else:
            i_start = fd.first_index(console, td.DECRYPT_START)
            assert i_psrc < i_hash < i_start < i_err, (
                f"expected primary read@{i_psrc} -> PLD_HASH_OK@{i_hash} -> "
                f"{td.DECRYPT_START}@{i_start} -> {slot_err}@{i_err}. "
                f"Console: {console}"
            )
            if self.defect == "iv":
                i_ok = fd.first_index(console, td.DECRYPT_OK)
                assert i_start < i_ok < i_err, (
                    f"wrong-IV CBC must complete decryption before TOC rejection; "
                    f"got start@{i_start}, ok@{i_ok}, error@{i_err}"
                )
        self.logger.info(
            "CHK-DECRYPT-ARM: primary@%d -> PLD_HASH_OK@%d -> %s@%d; "
            "DECRYPT_START count=%d, DECRYPT_OK count=%d",
            i_psrc,
            i_hash,
            slot_err,
            i_err,
            self._spec["decrypt_starts"],
            self._spec["decrypt_oks"],
        )

        # CHK-BACKUP-DECRYPTED: same fuse and engine, one field different; the control.
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
                i_bsrc,
                td.DECRYPT_START,
                i_bstart,
                td.DECRYPT_OK,
                i_bok,
                i_mok,
            )

        # CHK-STIMULUS-SERVED: the console cannot tell the rows apart; the served fields can.
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            OFF_ENCRYPTION_IV,
            self._packed_iv,
            "the primary manifest encryption_iv",
        )
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            OFF_ENCRYPTION_KDF_INPUT,
            self._packed_kdf,
            "the primary manifest encryption_kdf_input",
        )

        self.logger.info(
            "CHK-DECRYPT-INPUT-RULE: with %s wrong, the primary was refused "
            "%s@%d at the expected OCA stage; the backup was read@%d and booted",
            self._spec["what"],
            slot_err,
            i_err,
            i_bsrc,
        )
