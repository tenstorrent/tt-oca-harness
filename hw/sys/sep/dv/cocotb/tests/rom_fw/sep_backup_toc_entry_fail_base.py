# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases where a backup TOC entry breaks a per-image rule.

The primary is refused on its magic word, so the backup's TOC entry check is the only one that
fires. Members select the defect and plaintext or encrypted; the ROM must then halt.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_entry_fail_base(sep_backup_payload_fail_base):
    entry_defect: str = ""
    encrypted: bool = False

    primary_expected_error = ted.ERR_BAD_MAGIC

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.entry_defect in ted.DEFECT_TOKEN, (
            f"{cls.__name__} must declare entry_defect as one of "
            f"{list(ted.DEFECT_TOKEN)}, got {cls.entry_defect!r}"
        )
        cls.flash_image = ted.ENCRYPTED_IMAGE if cls.encrypted else ted.PLAINTEXT_IMAGE
        cls.efuse_preload = ted.ENCRYPTED_EFUSE if cls.encrypted else ted.PLAINTEXT_EFUSE
        cls.expected_error = ted.EXPECTED_ERROR[cls.entry_defect]
        cls.backup_defect_marker = ted.DEFECT_TOKEN[cls.entry_defect]

        # ERR_BAD_MAGIC is excluded: it is the primary's failover trigger, not a competing verdict.
        forbidden = ted.neighbouring_errors(cls.entry_defect, exclude=(ted.ERR_BAD_MAGIC,))
        forbidden += list(ted.other_payload_tokens(cls.entry_defect))
        forbidden += list(ted.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(ted.DECRYPT_START)
        cls.extra_forbidden = tuple(forbidden)

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            got = pm.is_encrypted(buf, slot)
            assert got == self.encrypted, (
                f"{slot} payload encrypted_payload flag is {int(got)} but this "
                f"member declares encrypted={self.encrypted}; the loaded image "
                f"({self.flash_image}) is not the one this cell is about"
            )
        self._payload_offset = pm.payload_base(buf, "backup") - mm.slot_base("backup")
        return super().mutate_flash_image(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        major, minor = mm.manifest_version(buf, "backup")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {major}.{minor}: the slot would be refused "
            f"by validate_manifest_header before the TOC is ever parsed"
        )
        assert mm.manifest_length(buf, "backup") == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {mm.manifest_length(buf, 'backup')}, "
            f"expected {mm.MANIFEST_SIZE}: BAD_LENGTH would pre-empt the TOC arm"
        )
        self._served = ted.plant(self.logger, buf, "backup", self.entry_defect)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        token = self.backup_defect_marker
        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_token = fd.first_index(console, token)
        i_err = fd.first_index(console, backup_err)

        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the backup's; the "
            f"primary is refused on its magic word before its payload is ever "
            f"parsed). Console: {console}"
        )

        if self.encrypted:
            for marker in (ted.DECRYPT_START, ted.DECRYPT_OK):
                k = fd.count(console, marker)
                assert k == 1, (
                    f"{marker} appeared {k} times, expected exactly 1 (the backup's; "
                    f"the primary is refused on its magic word before "
                    f"decrypt_payload runs). Console: {console}"
                )
            i_ds = fd.first_index(console, ted.DECRYPT_START)
            i_do = fd.first_index(console, ted.DECRYPT_OK)
            assert i_bsrc < i_ds < i_do < i_token, (
                f"expected backup read@{i_bsrc} -> {ted.DECRYPT_START}@{i_ds} -> "
                f"{ted.DECRYPT_OK}@{i_do} -> {token}@{i_token}: the backup's TOC "
                f"entry was not refused after its own payload decrypted. "
                f"Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: backup@%d -> %s@%d -> %s@%d -> %s@%d, each "
                "decryption marker exactly once",
                i_bsrc,
                ted.DECRYPT_START,
                i_ds,
                ted.DECRYPT_OK,
                i_do,
                token,
                i_token,
            )

        ted.assert_served_entry_field(
            self.logger,
            self._flash,
            "backup",
            self.entry_defect,
            self._served,
            self._payload_offset,
        )

        self.logger.info(
            "CHK-TOC-ENTRY-RULE: backup@%d violated %s, was announced %s@%d and "
            "refused %s@%d after its crypto chain passed; the run ended terminal "
            "with no slot accepted",
            i_bsrc,
            self.entry_defect,
            token,
            i_token,
            backup_err,
            i_err,
        )
