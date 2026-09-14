# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BACKUP's TOC claims a bad length or places image 0 too low; both slots fail, the ROM halts.

The terminal mirror of :mod:`sep_primary_toc_bound_fail_base`, and four members of
the same shape: ``{payload_image_exceeds_bound, toc_payload_size_mismatch} x
{plaintext, encrypted}``.

THE FAILOVER TRIGGER CANNOT INTERACT WITH THE ARM UNDER TEST. Reaching the
backup at all needs the primary refused first, and
``sep_backup_manifest_fail_base.corrupt_primary`` does it by overwriting the
primary's manifest identifier (``mm.set_identifier``). That produces
``MANIFEST_ERR_BAD_MAGIC``, which ``validate_manifest_header`` returns before any
hash, crypto or TOC work, so the trigger runs nowhere near the arm under test and
the primary's error code stays distinct from the backup's. The planted word is
``0x99999999``; the check reads only whether the identifier is TBL1.

THE PRIMARY'S REFUSAL IS WHY THIS FAMILY'S OWN CODE STAYS ATTRIBUTABLE, and the PLEN
members need that argument most. ``MANIFEST_ERR_BAD_LENGTH`` is reachable from
``validate_manifest_header`` as well as from the TOC agreement check, so a row whose
verdict is BAD_LENGTH has to show the code came from the later one. It does: the
primary dies on BAD_MAGIC, and the backup's BAD_LENGTH is required to appear after
the backup's ``CRYPTO_VALIDATE_OK``, which only a slot that cleared
``validate_manifest_header`` in full can reach.

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
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base


class sep_backup_toc_bound_fail_base(sep_backup_payload_fail_base):
    """Plant a TOC length or entry-0 bound defect in the backup; require a halt."""

    # --- member contract ---------------------------------------------------
    # tbd.BOUND or tbd.PLEN.
    bound_defect: str = ""
    # Whether this member's payload is encrypted; asserted against the image.
    encrypted: bool = False

    # The primary is refused on its magic word by the inherited corrupt_primary().
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
        # The arm announces itself, so the base's own CHK-BACKUP-DEFECT places
        # "which rule" after CRYPTO_VALIDATE_OK and inside the backup's attempt.
        cls.backup_defect_marker = tbd.DEFECT_TOKEN[cls.bound_defect]

        # Every code and token that would mean a different check ended the run. The
        # sibling arm's code AND its token are the swap-test defence: this row cannot
        # pass on the other family's verdict. ERR_BAD_MAGIC is excluded because it is
        # this scenario's own failover trigger, planted in the PRIMARY slot.
        forbidden = tbd.neighbouring_errors(cls.bound_defect,
                                            exclude=(tbd.ERR_BAD_MAGIC,))
        forbidden += list(tbd.other_payload_tokens(cls.bound_defect))
        forbidden += list(tbd.DECRYPT_FAILURE_TOKENS)
        if not cls.encrypted:
            forbidden.append(tbd.DECRYPT_START)
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
            f"expected {mm.MANIFEST_SIZE}: validate_manifest_header would return "
            f"BAD_LENGTH from a different check with the same code"
        )
        self._served = tbd.plant(self.logger, buf, "backup", self.bound_defect)

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

        # CHK-BOUND-COUNT: the arm fired once, for the backup. The primary is refused
        # on its magic word and never parses a TOC, so a second occurrence would mean
        # the stimulus landed in both slots and the run is not this scenario.
        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the backup's; the "
            f"primary is refused on its magic word before its payload is ever "
            f"parsed). Console: {console}"
        )

        # CHK-DECRYPT-ARM: exactly one slot decrypted, it was the backup, and its
        # decryption SUCCEEDED before the TOC was refused.
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

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes at
        # this row's field address, in this row's slot. `self._flash` is published by
        # sep_backup_manifest_fail_base for exactly this kind of device-side check.
        # On the encrypted members the ADDRESS is what separates this cell from the
        # primary one, because the two slots' ciphertexts agree this early in the CBC
        # chain.
        tbd.assert_served_bound_field(self.logger, self._flash, "backup",
                                      self.bound_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-BOUND-RULE: backup@%d violated %s, was announced %s@%d and "
            "refused %s@%d after its crypto chain passed; the run ended terminal "
            "with no slot accepted", i_bsrc, self.bound_defect, token, i_token,
            backup_err, i_err,
        )
