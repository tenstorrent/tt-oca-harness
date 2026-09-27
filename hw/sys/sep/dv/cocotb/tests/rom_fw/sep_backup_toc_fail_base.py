# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases where the backup TOC has a bad major version or image count.

These checks print no token, so members are graded on the error code, forbidden sibling codes and
the bytes the flash device served. The primary is refused on its magic word; the ROM must halt.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_fail_base(sep_backup_payload_fail_base):
    toc_field: str = ""
    encrypted: bool = False

    # These TOC checks return without a console token.
    backup_defect_marker = ""
    requires_defect_marker = False
    primary_expected_error = td.ERR_BAD_MAGIC

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.toc_field in td.FIELDS, (
            f"{cls.__name__} must declare toc_field as one of {list(td.FIELDS)}, "
            f"got {cls.toc_field!r}"
        )
        cls.flash_image = td.ENCRYPTED_IMAGE if cls.encrypted else td.PLAINTEXT_IMAGE
        cls.efuse_preload = td.ENCRYPTED_EFUSE if cls.encrypted else td.PLAINTEXT_EFUSE
        cls.expected_error = td.EXPECTED_ERROR[cls.toc_field]

        forbidden = [
            f"MANIFEST_ERR=0x{td.sibling_error(cls.toc_field):08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_VERSION:08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_LENGTH:08x}",
            f"MANIFEST_ERR=0x{td.ERR_BAD_TOC_ID:08x}",
            f"MANIFEST_ERR=0x{td.ERR_PAYLOAD_TOO_LARGE:08x}",
            f"MANIFEST_ERR=0x{td.ERR_NO_BL1_IMAGE:08x}",
        ]
        forbidden += list(td.OTHER_PAYLOAD_TOKENS) + list(td.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(td.DECRYPT_START)
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
        self._served = td.plant(self.logger, buf, "backup", self.toc_field)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_err = fd.first_index(console, backup_err)

        if self.encrypted:
            for marker in (td.DECRYPT_START, td.DECRYPT_OK):
                n = fd.count(console, marker)
                assert n == 1, (
                    f"{marker} appeared {n} times, expected exactly 1 (the "
                    f"backup's; the primary is refused on its magic word before "
                    f"decrypt_payload runs). Console: {console}"
                )
            i_ds = fd.first_index(console, td.DECRYPT_START)
            i_do = fd.first_index(console, td.DECRYPT_OK)
            assert i_bsrc < i_ds < i_do < i_err, (
                f"expected backup read@{i_bsrc} -> {td.DECRYPT_START}@{i_ds} -> "
                f"{td.DECRYPT_OK}@{i_do} -> {backup_err}@{i_err}: the backup's TOC "
                f"was not refused after its own payload decrypted. Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: backup@%d -> %s@%d -> %s@%d -> %s@%d, each "
                "decryption marker exactly once",
                i_bsrc,
                td.DECRYPT_START,
                i_ds,
                td.DECRYPT_OK,
                i_do,
                backup_err,
                i_err,
            )

        td.assert_served_toc_field(
            self.logger, self._flash, "backup", self.toc_field, self._served, self._payload_offset
        )

        self.logger.info(
            "CHK-TOC-RULE: backup@%d declared TOC %s = %d and was refused %s@%d "
            "after its crypto chain passed; the run ended terminal with no slot "
            "accepted",
            i_bsrc,
            self.toc_field,
            td.PLANTED[self.toc_field],
            backup_err,
            i_err,
        )
