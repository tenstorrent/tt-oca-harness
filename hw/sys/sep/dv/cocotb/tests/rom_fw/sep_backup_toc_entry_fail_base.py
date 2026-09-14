# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BACKUP's TOC entries break a per-image rule; both slots are refused and the ROM halts.

The terminal mirror of :mod:`sep_primary_toc_entry_fail_base`, and four members of
the same shape: ``{images_out_of_order, invalid_payload_image_size} x {plaintext,
encrypted}``.

THE FAILOVER TRIGGER CANNOT INTERACT WITH THE ARM UNDER TEST. Reaching the
backup at all needs the primary refused first, and
``sep_backup_manifest_fail_base.corrupt_primary`` does it by overwriting the
primary's manifest identifier (``mm.set_identifier``). That produces
``MANIFEST_ERR_BAD_MAGIC``, which ``validate_manifest_header`` returns before any
hash, crypto or TOC work, so the trigger runs nowhere near the arm under test and
the primary's error code stays distinct from the backup's. The planted word is
``0x99999999``; the check reads only whether the identifier is TBL1.

WHY THIS FAMILY NEEDS ITS OWN BASE. :mod:`sep_backup_payload_fail_base` already
grades the right stage and already supports an arm that prints a token, so this base
adds only what is specific to the per-image arms: the sibling arm's code is
FORBIDDEN, the sibling arm's TOKEN is forbidden, and the flash device must be shown
to have served this row's exact planted bytes at the mutated field's exact address.
That last one is what separates two rows whose consoles agree on everything except
one index.

DECRYPTION COUNTS DIFFER FROM THE PRIMARY FAMILY, and that is the encrypted members'
own evidence. Here the primary dies on its magic word long before ``decrypt_payload``,
so an encrypted member requires ``DECRYPT_START`` and ``DECRYPT_OK`` EXACTLY ONCE --
the backup's -- where the primary family requires two. A plaintext member forbids
``DECRYPT_START`` outright.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_entry_fail_base(sep_backup_payload_fail_base):
    """Plant a per-image TOC defect in the backup; require a terminal failure."""

    # --- member contract ---------------------------------------------------
    # ted.ORDER or ted.SIZE.
    entry_defect: str = ""
    # Whether this member's payload is encrypted; asserted against the image.
    encrypted: bool = False

    # The primary is refused on its magic word by the inherited corrupt_primary().
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
        # The arm announces itself, and the token carries the entry index, so the
        # base's own CHK-BACKUP-DEFECT places "which rule, on which entry" after
        # CRYPTO_VALIDATE_OK and inside the backup's attempt.
        cls.backup_defect_marker = ted.DEFECT_TOKEN[cls.entry_defect]

        # Every code and token that would mean a different check ended the run. The
        # sibling arm's code AND its token are the swap-test defence: this row cannot
        # pass on the other family's verdict. ERR_BAD_MAGIC is excluded because it is
        # this scenario's own failover trigger, planted in the PRIMARY slot.
        forbidden = ted.neighbouring_errors(cls.entry_defect,
                                            exclude=(ted.ERR_BAD_MAGIC,))
        forbidden += list(ted.other_payload_tokens(cls.entry_defect))
        forbidden += list(ted.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(ted.DECRYPT_START)
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
        self._served = ted.plant(self.logger, buf, "backup", self.entry_defect)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        token = self.backup_defect_marker
        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_token = fd.first_index(console, token)
        i_err = fd.first_index(console, backup_err)

        # CHK-ENTRY-COUNT: the arm fired once, for the backup. The primary is refused
        # on its magic word and never parses a TOC, so a second occurrence would mean
        # the stimulus landed in both slots and the run is not this scenario.
        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the backup's; the "
            f"primary is refused on its magic word before its payload is ever "
            f"parsed). Console: {console}"
        )

        # CHK-DECRYPT-ARM: exactly one slot decrypted, it was the backup, and its
        # decryption SUCCEEDED before the TOC entry was refused.
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
                "decryption marker exactly once", i_bsrc, ted.DECRYPT_START, i_ds,
                ted.DECRYPT_OK, i_do, token, i_token,
            )

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes at
        # this row's field address. `self._flash` is published by
        # sep_backup_manifest_fail_base for exactly this kind of device-side check.
        ted.assert_served_entry_field(self.logger, self._flash, "backup",
                                      self.entry_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-ENTRY-RULE: backup@%d violated %s, was announced %s@%d and "
            "refused %s@%d after its crypto chain passed; the run ended terminal "
            "with no slot accepted", i_bsrc, self.entry_defect, token, i_token,
            backup_err, i_err,
        )
