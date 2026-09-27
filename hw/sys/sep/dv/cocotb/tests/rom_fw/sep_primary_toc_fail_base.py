# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY carries a silent TOC defect; the backup boots.

Members set toc_field and encrypted. The TOC check runs after the signature and
decryption, so the primary reaches SIG_VALID before it is refused.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_fail_base(sep_primary_fail_backup_boot_base):
    # --- member contract ---------------------------------------------------
    # "version_major" or "image_count".
    toc_field: str = ""
    # Selects the encrypted image and fuse preload; checked against the image's own flag.
    encrypted: bool = False

    # The TOC header arms print no token of their own.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC is refused.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.toc_field in td.FIELDS, (
            f"{cls.__name__} must declare toc_field as one of {list(td.FIELDS)}, "
            f"got {cls.toc_field!r}"
        )
        cls.flash_image = td.ENCRYPTED_IMAGE if cls.encrypted else td.PLAINTEXT_IMAGE
        cls.efuse_preload = td.ENCRYPTED_EFUSE if cls.encrypted else td.PLAINTEXT_EFUSE
        cls.primary_expected_error = td.EXPECTED_ERROR[cls.toc_field]
        cls.backup_sealed_check_toc = not cls.encrypted

        required = ["MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Forbid every other structural code; the accepted backup prints no MANIFEST_ERR=.
        forbidden = [
            f"MANIFEST_ERR=0x{td.sibling_error(cls.toc_field):08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_MAGIC:08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_VERSION:08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_LENGTH:08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_TOC_ID:08x}",
            f"MANIFEST_ERR=0x{td.ERR_PAYLOAD_TOO_LARGE:08x}",
            f"MANIFEST_ERR=0x{td.ERR_NO_BL1_IMAGE:08x}",
            "CRYPTO_FAIL=",
            "MANIFEST_ALL_FAILED",
        ]
        forbidden += list(td.OTHER_PAYLOAD_TOKENS) + list(td.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [td.DECRYPT_START, td.DECRYPT_OK]
        else:
            # decrypt_payload() runs only for encrypted_payload; no DECRYPT_START proves plaintext.
            forbidden.append(td.DECRYPT_START)
        cls.extra_required = tuple(required)
        cls.extra_forbidden = tuple(forbidden)

    # --- stimulus ----------------------------------------------------------
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Fail here if the loaded image does not match the declared encryption.
        for slot in ("primary", "backup"):
            got = pm.is_encrypted(buf, slot)
            assert got == self.encrypted, (
                f"{slot} payload encrypted_payload flag is {int(got)} but this "
                f"member declares encrypted={self.encrypted}; the loaded image "
                f"({self.flash_image}) is not the one this cell is about"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        # Keep the checks ahead of validate_manifest_payload satisfiable so the TOC arm is reached.
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: the slot would be "
            f"refused by validate_manifest_header before the TOC is ever parsed"
        )
        assert mm.manifest_length(buf, "primary") == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {mm.manifest_length(buf, 'primary')}, "
            f"expected {mm.MANIFEST_SIZE}: BAD_LENGTH would pre-empt the TOC arm"
        )
        self._served = td.plant(self.logger, buf, "primary", self.toc_field)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # The arm is silent, so its error code is the only ROM-side attribution.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

        # The primary's TOC must be refused after its own payload decrypted, not instead of it.
        if self.encrypted:
            for marker in (td.DECRYPT_START, td.DECRYPT_OK):
                n = fd.count(console, marker)
                assert n == 2, (
                    f"{marker} appeared {n} times, expected exactly 2 (the mutated "
                    f"primary's and the recovering backup's). Console: {console}"
                )
            i_ds = fd.first_index(console, td.DECRYPT_START)
            i_do = fd.first_index(console, td.DECRYPT_OK)
            assert i_psrc < i_ds < i_do < i_err, (
                f"expected primary read@{i_psrc} -> {td.DECRYPT_START}@{i_ds} -> "
                f"{td.DECRYPT_OK}@{i_do} -> {slot_err}@{i_err}: the primary's TOC "
                f"was not refused after its own payload decrypted. Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: primary@%d -> %s@%d -> %s@%d -> %s@%d, and both "
                "markers appear twice (primary and recovering backup)",
                i_psrc,
                td.DECRYPT_START,
                i_ds,
                td.DECRYPT_OK,
                i_do,
                slot_err,
                i_err,
            )

        # Only the served bytes separate cells that share an error code.
        td.assert_served_toc_field(
            self.logger, flash, "primary", self.toc_field, self._served, self._payload_offset
        )

        self.logger.info(
            "CHK-TOC-RULE: primary@%d declared TOC %s = %d and was refused %s@%d "
            "inside its own attempt, after its signature verified; the untouched "
            "backup was read@%d and booted",
            i_psrc,
            self.toc_field,
            td.PLANTED[self.toc_field],
            slot_err,
            i_err,
            i_bsrc,
        )
