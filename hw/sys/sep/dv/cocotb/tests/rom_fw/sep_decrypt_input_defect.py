# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCA AES-256 decryption-input defects with a healthy recovery slot.

The erased CLASS_KEY, wrong IV and wrong KDF context each fail at a different control
point after the primary's signature verifies.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_SEP_ROOT = Path(__file__).resolve().parents[4]
_BUILD_DIR = _SEP_ROOT / "bootrom" / "prod" / "build"
_EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"

OFF_ENCRYPTION_IV = mm.OFF_ENCRYPTION_IV
OFF_ENCRYPTION_KDF_INPUT = mm.OFF_ENCRYPTION_KDF_INPUT

# Golden inputs the images were packed with; the CLASS_KEY fuse must hold GOLDEN_CLASS_KEY.
GOLDEN_KDF_INPUT = bytes.fromhex("a5" * 16 + "b6" * 16 + "c7" * 16 + "d8" * 16)
GOLDEN_CLASS_KEY = pm.OCA_TEST_CLASS_KEY
GOLDEN_IV = bytes(range(0x10, 0x20))
# What an unprogrammed CLASS_KEY fuse reads.
BAD_CLASS_KEY = bytes(32)
# Flipping IV byte 0 flips plaintext byte 0 only: the first byte of the PTOC magic.
_IV_FLIP_BYTE = 0

_DECRYPT_OK = "DECRYPT_OK"
_PAD_BAD = "AES_PAD_BAD"
_CLASS_KEY_EMPTY = "DECRYPT_CLASS_KEY_EMPTY"
# Outcome markers of plat_decrypt_payload(); each row names the one it must print.
_DECRYPT_OUTCOMES = (
    _DECRYPT_OK,
    _PAD_BAD,
    _CLASS_KEY_EMPTY,
    "DECRYPT_NO_SECRET",
    "KDF_HMAC_FAIL",
    "KDF_FAIL",
    "AES_DEC_FAIL",
)

DEFECTS = {
    "class_key": {
        "image": "invalid_class_key.bin",
        "efuse": "sep_efuse_lc_prod_bad_class_key.toml",
        "class_key": BAD_CLASS_KEY,
        "backup_encrypted": False,
        "expected_error": mm.boot_err("OCA_FAIL_NO_PROVISIONED_SECRET"),
        "outcome": _CLASS_KEY_EMPTY,
        "what": "the CLASS_KEY fuse the KBKDF derives the payload key from",
    },
    "iv": {
        "image": "oca_encrypted_boot.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "expected_error": mm.boot_err("OCA_FAIL_PAYLOAD_HASH_CHAIN"),
        "outcome": _DECRYPT_OK,
        "what": "the primary manifest's encryption_iv",
    },
    "kdf_input": {
        "image": "oca_encrypted_boot.bin",
        "efuse": "sep_efuse_lc_prod_class_key.toml",
        "class_key": GOLDEN_CLASS_KEY,
        "backup_encrypted": True,
        "expected_error": mm.boot_err("OCA_FAIL_DECRYPT"),
        "outcome": _PAD_BAD,
        "what": "the primary manifest's encryption_kdf_input",
    },
}


class sep_decrypt_input_defect_base(sep_primary_fail_backup_boot_base):
    defect: str = ""

    # All three defects are downstream of a verified signature, inside the payload stage.
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"

    def __init_subclass__(cls, **kwargs) -> None:
        # Derived fields first: the base validates the contract in its own hook.
        if cls.defect:
            assert cls.defect in DEFECTS, (
                f"{cls.__name__} must declare defect as one of {list(DEFECTS)}, got {cls.defect!r}"
            )
            spec = DEFECTS[cls.defect]
            cls.flash_image = str(_BUILD_DIR / spec["image"])
            cls.efuse_preload = _EFUSE_DIR / spec["efuse"]
            cls.primary_expected_error = spec["expected_error"]
            outcome = spec["outcome"]
            # DECRYPT_OK is not the defect's marker: the IV row's refusal is silent after it.
            if outcome == _DECRYPT_OK:
                cls.primary_ordered = (outcome,)
                cls.primary_defect_marker = f"MANIFEST_ERR=0x{cls.primary_expected_error:08x}"
            else:
                cls.primary_defect_marker = outcome
            cls.primary_absent = tuple(m for m in _DECRYPT_OUTCOMES if m != outcome)
            cls.extra_required = ("BL1_COPIED", "BL1_JUMP=")
        super().__init_subclass__(**kwargs)

    @property
    def _spec(self) -> dict:
        return DEFECTS[self.defect]

    def corrupt_primary(self, buf: bytearray) -> None:
        for slot in ("primary", "backup"):
            iv, kdf = pm.golden_iv(buf, slot), pm.manifest_kdf_input(buf, slot)
            assert (iv, kdf) == (GOLDEN_IV, GOLDEN_KDF_INPUT) or not pm.is_encrypted(buf, slot), (
                f"{slot} of {self.flash_image} carries IV={iv.hex()} KDF={kdf.hex()}, not "
                f"the golden inputs; the shipped image is not the baseline this row mutates"
            )
        assert pm.is_encrypted(buf, "primary"), (
            f"primary payload has encrypted_payload clear in {self.flash_image}: the ROM "
            f"would not decrypt, so nothing about decryption is being tested"
        )
        got_backup = pm.is_encrypted(buf, "backup")
        assert got_backup == self._spec["backup_encrypted"], (
            f"backup encrypted_payload is {int(got_backup)} but this row needs "
            f"{int(self._spec['backup_encrypted'])}; {self.flash_image} is not its image"
        )

        golden = bytes(buf)
        if self.defect == "iv":
            bad_iv = bytearray(GOLDEN_IV)
            bad_iv[_IV_FLIP_BYTE] ^= 0xFF
            pm.set_encryption_iv(buf, "primary", bytes(bad_iv))
            # Only the magic byte changes, so the hash chain is the first check to refuse it.
            ok, _plain = pm.rom_view_decrypt(buf, "primary")
            assert ok, "a wrong IV broke the PKCS#7 pad; the row would land on AES_PAD_BAD"
            diff = pm.plaintext_diff(golden, bytes(buf), "primary")
            assert diff == [range(_IV_FLIP_BYTE, _IV_FLIP_BYTE + 1)], (
                f"wrong IV changed plaintext bytes {diff}, expected only byte "
                f"{_IV_FLIP_BYTE} of the PTOC magic"
            )
            bad = pm.spec_rule_violations(buf, "primary")
            assert bad == [], (
                f"wrong-IV plaintext breaks TOC rules {bad}; the verdict would not be the chain's"
            )
        elif self.defect == "kdf_input":
            bad_kdf = bytearray(GOLDEN_KDF_INPUT)
            bad_kdf[0] ^= 0xFF
            pm.set_encryption_kdf_input(buf, "primary", bytes(bad_kdf))
            assert pm.oca_aes256_key(GOLDEN_CLASS_KEY, bytes(bad_kdf)) != pm.oca_aes256_key(
                GOLDEN_CLASS_KEY, GOLDEN_KDF_INPUT
            ), "the defective KDF context derived the golden key"
            ok, _plain = pm.rom_view_decrypt(buf, "primary")
            assert not ok, (
                "the wrong key still produced a valid PKCS#7 pad; the ROM would reach the "
                "TOC checks instead of AES_PAD_BAD"
            )
        else:
            # The CLASS_KEY row keeps the packer's seal; only the fuse differs.
            pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")

        self._packed_iv = pm.golden_iv(buf, "primary")
        self._packed_kdf = pm.manifest_kdf_input(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-FIELD: %s is wrong; primary IV=%s (golden=%s), KDF input=%s "
            "(golden=%s), CLASS_KEY golden=%s; expected MANIFEST_ERR=0x%08x after %s",
            self._spec["what"],
            self._packed_iv.hex(),
            self._packed_iv == GOLDEN_IV,
            self._packed_kdf.hex(),
            self._packed_kdf == GOLDEN_KDF_INPUT,
            self._spec["class_key"] == GOLDEN_CLASS_KEY,
            self.primary_expected_error,
            self._spec["outcome"],
        )

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
                f"OTP CLASS_KEY is 0x{got:064x}, not the packing key 0x{golden:064x}: "
                f"the key would be wrong as well as {self._spec['what']}"
            )
        self.logger.info(
            "CHK-STIMULUS-CLASS-KEY: OTP CLASS_KEY=0x%064x, packing key=0x%064x, equal=%s",
            got,
            golden,
            got == golden,
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        # One DECRYPT_OK per decrypting slot; the encrypted backup is the control.
        want = int(self.defect == "iv") + int(self._spec["backup_encrypted"])
        n = oc.count(console, _DECRYPT_OK)
        assert n == want, (
            f"{_DECRYPT_OK} appeared {n} times, expected {want} for the {self.defect} row. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-DECRYPT-ARM PASS: %s -> primary printed %s and MANIFEST_ERR=0x%08x; "
            "DECRYPT_OK count=%d",
            self._spec["what"],
            self._spec["outcome"],
            self.primary_expected_error,
            n,
        )

        # The console cannot tell the rows apart; the served fields can.
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
