# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BACKUP carries a silent TOC defect; both slots are refused and the ROM halts.

The terminal mirror of :mod:`sep_primary_toc_fail_base`, and four members of the
same shape: ``{version_major, image_count} x {plaintext, encrypted}``.

THE FAILOVER TRIGGER IS THE REFERENCE'S OWN. Every backup scenario in
``tb/cocotb_tests/sep_firmware_payload_validation_test.py`` pairs its backup
mutation with ``primary.manifest.manifest_identifier = 99``, which makes the
primary fail on its magic word. ``sep_backup_manifest_fail_base.corrupt_primary``
plants the same defect by default (``mm.set_identifier``) and it produces
``MANIFEST_ERR_BAD_MAGIC``, refused by ``validate_manifest_header`` before any
hash, crypto or TOC work -- so the trigger cannot interact with the arm under
test, and the primary's error code stays distinct from the backup's. The planted
word differs in VALUE from the reference's -- ``0x99999999`` rather than decimal
99 -- because the mutator writes the whole 32-bit identifier. Both are "not
TBL1", which is the only property the check reads.

WHY THIS FAMILY NEEDS ITS OWN BASE. :mod:`sep_backup_payload_fail_base` grades
the right stage -- the backup's crypto chain passes and then
``validate_manifest_payload`` refuses it, so ``RSA_VERIFY_START`` appears and
``CRYPTO_FAIL=`` does not -- but its members all print an arm-specific token such
as ``NO_BL1_IMAGE``. The TOC major-version and image-count arms return silently
(``bootrom/prod/src/manifest_load.c``), so this base clears
``requires_defect_marker`` and compensates with two things the token would
otherwise have carried: the sibling arm's error code is FORBIDDEN, and the flash
device must be shown to have served this row's exact planted bytes at the field's
exact address.

DECRYPTION COUNTS DIFFER FROM THE PRIMARY FAMILY, and that is the encrypted
members' own evidence. Here the primary dies on its magic word long before
``decrypt_payload``, so an encrypted member requires ``DECRYPT_START`` and
``DECRYPT_OK`` EXACTLY ONCE -- the backup's -- where the primary family requires
two. A plaintext member forbids ``DECRYPT_START`` outright.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_fail_base(sep_backup_payload_fail_base):
    """Plant a silent TOC defect in the backup; require a terminal failure."""

    # --- member contract ---------------------------------------------------
    # "version_major" or "image_count".
    toc_field: str = ""
    # Whether this member's payload is encrypted; asserted against the image.
    encrypted: bool = False

    # The arm returns without printing; see the module docstring.
    backup_defect_marker = ""
    requires_defect_marker = False
    # The primary is refused on its magic word by the inherited corrupt_primary().
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

        # Every code and token that would mean a different check ended the run.
        # The sibling TOC arm's code is the swap-test defence: this row cannot pass
        # on the other family's verdict.
        forbidden = [f"MANIFEST_ERR=0x{td.sibling_error(cls.toc_field):08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_VERSION:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_LENGTH:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_TOC_ID:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_PAYLOAD_TOO_LARGE:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_NO_BL1_IMAGE:08x}"]
        forbidden += list(td.OTHER_PAYLOAD_TOKENS) + list(td.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(td.DECRYPT_START)
        cls.extra_forbidden = tuple(forbidden)

    # --- stimulus ----------------------------------------------------------
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

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_err = fd.first_index(console, backup_err)

        # CHK-DECRYPT-ARM: exactly one slot decrypted, it was the backup, and its
        # decryption SUCCEEDED before the TOC was refused. The primary never gets
        # there -- it dies on its magic word -- so a second occurrence would mean
        # the failover trigger did not fire where this scenario assumes.
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
                "decryption marker exactly once", i_bsrc, td.DECRYPT_START, i_ds,
                td.DECRYPT_OK, i_do, backup_err, i_err,
            )

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes
        # at this row's field address. `self._flash` is published by
        # sep_backup_manifest_fail_base for exactly this kind of device-side check.
        td.assert_served_toc_field(self.logger, self._flash, "backup",
                                   self.toc_field, self._served,
                                   self._payload_offset)

        self.logger.info(
            "CHK-TOC-RULE: backup@%d declared TOC %s = %d and was refused %s@%d "
            "after its crypto chain passed; the run ended terminal with no slot "
            "accepted", i_bsrc, self.toc_field, td.PLANTED[self.toc_field],
            backup_err, i_err,
        )
