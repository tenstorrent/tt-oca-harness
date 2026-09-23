# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base for testcases where the backup TOC has a bad length or a low image-0 bound.

The primary is refused on its magic word, so the backup's TOC bound check is the only one that
fires. Members select the defect and plaintext or encrypted; the ROM must then halt.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_bound_fail_base(sep_backup_payload_fail_base):

    bound_defect: str = ""
    encrypted: bool = False

    primary_expected_error = tbd.ERR_BAD_MAGIC

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        assert cls.bound_defect in tbd.DEFECT_TOKEN, (
            f"{cls.__name__} must declare bound_defect as one of "
            f"{list(tbd.DEFECT_TOKEN)}, got {cls.bound_defect!r}"
        )
        cls.flash_image = tbd.ENCRYPTED_IMAGE if cls.encrypted else tbd.PLAINTEXT_IMAGE
        cls.efuse_preload = tbd.ENCRYPTED_EFUSE if cls.encrypted else tbd.PLAINTEXT_EFUSE
        cls.expected_error = tbd.EXPECTED_ERROR[cls.bound_defect]
        cls.backup_defect_marker = tbd.DEFECT_TOKEN[cls.bound_defect]

        # ERR_BAD_MAGIC is excluded: it is the primary's failover trigger, not a competing verdict.
        forbidden = tbd.neighbouring_errors(cls.bound_defect,
                                            exclude=(tbd.ERR_BAD_MAGIC,))
        forbidden += list(tbd.other_payload_tokens(cls.bound_defect))
        forbidden += list(tbd.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(tbd.DECRYPT_START)
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
            f"expected {mm.MANIFEST_SIZE}: validate_manifest_header would return "
            f"BAD_LENGTH from a different check with the same code"
        )
        self._served = tbd.plant(self.logger, buf, "backup", self.bound_defect)

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
            for marker in (tbd.DECRYPT_START, tbd.DECRYPT_OK):
                k = fd.count(console, marker)
                assert k == 1, (
                    f"{marker} appeared {k} times, expected exactly 1 (the backup's; "
                    f"the primary is refused on its magic word before "
                    f"decrypt_payload runs). Console: {console}"
                )
            i_ds = fd.first_index(console, tbd.DECRYPT_START)
            i_do = fd.first_index(console, tbd.DECRYPT_OK)
            assert i_bsrc < i_ds < i_do < i_token, (
                f"expected backup read@{i_bsrc} -> {tbd.DECRYPT_START}@{i_ds} -> "
                f"{tbd.DECRYPT_OK}@{i_do} -> {token}@{i_token}: the backup's TOC "
                f"was not refused after its own payload decrypted. "
                f"Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: backup@%d -> %s@%d -> %s@%d -> %s@%d, each "
                "decryption marker exactly once", i_bsrc, tbd.DECRYPT_START, i_ds,
                tbd.DECRYPT_OK, i_do, token, i_token,
            )

        # Encrypted members: only the address separates the slots, as both ciphertexts agree here.
        tbd.assert_served_bound_field(self.logger, self._flash, "backup",
                                      self.bound_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-BOUND-RULE: backup@%d violated %s, was announced %s@%d and "
            "refused %s@%d after its crypto chain passed; the run ended terminal "
            "with no slot accepted", i_bsrc, self.bound_defect, token, i_token,
            backup_err, i_err,
        )
