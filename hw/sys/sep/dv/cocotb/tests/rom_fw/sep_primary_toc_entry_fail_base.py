# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY's TOC entries break a per-image rule; the backup boots.

Members set entry_defect and encrypted. The TOC check runs after the signature and
decryption, so the primary reaches SIG_VALID before it is refused.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_entry_fail_base(sep_primary_fail_backup_boot_base):

    # --- member contract ---------------------------------------------------
    # ted.ORDER or ted.SIZE.
    entry_defect: str = ""
    # Selects the encrypted image and fuse preload; checked against the image's own flag.
    encrypted: bool = False

    # The base would pair a defect marker with CRYPTO_FAIL=, which this arm never prints.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC entry is refused.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.entry_defect in ted.DEFECT_TOKEN, (
            f"{cls.__name__} must declare entry_defect as one of "
            f"{list(ted.DEFECT_TOKEN)}, got {cls.entry_defect!r}"
        )
        cls.flash_image = ted.ENCRYPTED_IMAGE if cls.encrypted else ted.PLAINTEXT_IMAGE
        cls.efuse_preload = ted.ENCRYPTED_EFUSE if cls.encrypted else ted.PLAINTEXT_EFUSE
        cls.primary_expected_error = ted.EXPECTED_ERROR[cls.entry_defect]
        cls.backup_sealed_check_toc = not cls.encrypted

        required = [ted.DEFECT_TOKEN[cls.entry_defect],
                    "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Forbid every other code; the accepted backup prints no MANIFEST_ERR=.
        forbidden = ted.neighbouring_errors(cls.entry_defect)
        forbidden += ["CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        forbidden += list(ted.other_payload_tokens(cls.entry_defect))
        forbidden += list(ted.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [ted.DECRYPT_START, ted.DECRYPT_OK]
        else:
            # decrypt_payload() runs only for encrypted_payload; no DECRYPT_START proves plaintext.
            forbidden.append(ted.DECRYPT_START)
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
        self._served = ted.plant(self.logger, buf, "primary", self.entry_defect)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        token = ted.DEFECT_TOKEN[self.entry_defect]
        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # Token (with entry index) and error code must both be the primary's, in order, once each.
        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the primary's). "
            f"Console: {console}"
        )
        i_token = fd.assert_slot_attributed(console, token, after=i_psrc,
                                            before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_token,
                                          before=i_bsrc)

        # The primary's TOC entry must be refused after its payload decrypted, not instead of it.
        if self.encrypted:
            for marker in (ted.DECRYPT_START, ted.DECRYPT_OK):
                k = fd.count(console, marker)
                assert k == 2, (
                    f"{marker} appeared {k} times, expected exactly 2 (the mutated "
                    f"primary's and the recovering backup's). Console: {console}"
                )
            i_ds = fd.first_index(console, ted.DECRYPT_START)
            i_do = fd.first_index(console, ted.DECRYPT_OK)
            assert i_psrc < i_ds < i_do < i_token, (
                f"expected primary read@{i_psrc} -> {ted.DECRYPT_START}@{i_ds} -> "
                f"{ted.DECRYPT_OK}@{i_do} -> {token}@{i_token}: the primary's TOC "
                f"entry was not refused after its own payload decrypted. "
                f"Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: primary@%d -> %s@%d -> %s@%d -> %s@%d, and both "
                "markers appear twice (primary and recovering backup)",
                i_psrc, ted.DECRYPT_START, i_ds, ted.DECRYPT_OK, i_do, token, i_token,
            )

        # The device must serve this row's planted bytes at this row's field address.
        ted.assert_served_entry_field(self.logger, flash, "primary",
                                      self.entry_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-ENTRY-RULE: primary@%d violated %s, was announced %s@%d and "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, self.entry_defect, token, i_token, slot_err, i_err, i_bsrc,
        )
