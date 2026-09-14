# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY's TOC entries break a per-image rule; the backup boots.

Four members: ``{images_out_of_order, invalid_payload_image_size} x {plaintext,
encrypted}``. They share everything except which per-image rule is violated and
which of the two shipped images is loaded, and the base asserts both of those
rather than letting a member declare them and go unchecked.

WHY THE PRIMARY REACHES THE VERIFIER HERE, unlike most members of
``sep_primary_fail_backup_boot_base``. ``validate_manifest_payload`` runs AFTER
``manifest_crypto_validate`` (``bootrom/prod/src/manifest_load.c`` states the
required order: security version -> signature -> payload hash over ciphertext ->
decrypt -> TOC, with the TOC last precisely because an encrypted payload's TOC is
itself ciphertext). The stimulus re-seals the slot, so the primary's signature is
genuine and verifies. Both ``primary_expected_rsa_starts`` and
``primary_expected_sig_valids`` are therefore 1, and the base's own checks then
require the primary's ``RSA_VERIFY_START`` and ``SIG_VALID`` to sit inside the
primary attempt -- positive evidence that the rejection is downstream of the whole
crypto chain rather than an early structural refusal wearing the right error code.

WHY THE TOKEN IS DECLARED THROUGH ``extra_required`` RATHER THAN
``primary_defect_marker``. Both arms here DO print, unlike the header arms of
:mod:`sep_primary_toc_fail_base`. But ``sep_primary_fail_backup_boot_base._markers``
couples ``primary_defect_marker`` to a required ``CRYPTO_FAIL=`` line, and this
family never produces one: ``manifest_load.c`` prints ``CRYPTO_FAIL=`` only when
``manifest_crypto_validate`` fails, and these rejections happen after it succeeds.
So the token is required through ``extra_required`` and attributed by
:meth:`check_transport` below, which places it inside the primary's own attempt --
the same claim ``primary_defect_marker`` would have made, without the marker that
does not belong to this arm.

WHAT SEPARATES THE ENCRYPTED MEMBERS FROM THE PLAINTEXT ONES, on the console rather
than by assertion. An encrypted member requires ``DECRYPT_START`` and ``DECRYPT_OK``
EXACTLY TWICE -- once for the mutated primary, once for the recovering backup -- and
requires the primary's pair to sit inside the primary attempt. A plaintext member
FORBIDS ``DECRYPT_START`` outright. So the two cells cannot satisfy each other's
checks, and neither can satisfy them by accident: the image itself decides, and
:meth:`mutate_flash_image` asserts the loaded image's encryption flag matches what
the member declares.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_entry_fail_base(sep_primary_fail_backup_boot_base):
    """Plant a per-image TOC defect in the primary, require a failover and a boot."""

    # --- member contract ---------------------------------------------------
    # ted.ORDER or ted.SIZE.
    entry_defect: str = ""
    # Whether this member's payload is encrypted. Decides the image, the fuse
    # preload and the decryption evidence; asserted against the image's own flag.
    encrypted: bool = False

    # See the module docstring: this arm prints a token, but not the one the base's
    # marker machinery would pair with it.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC entry
    # is refused.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        """Derive the image, the fuse preload and the marker lists from the cell.

        Done at class-definition time rather than per instance, so a member is one
        pair of declarations and the two attributes that decide the scenario cannot
        drift apart from the markers that grade it.
        """
        super().__init_subclass__(**kwargs)
        assert cls.entry_defect in ted.DEFECT_TOKEN, (
            f"{cls.__name__} must declare entry_defect as one of "
            f"{list(ted.DEFECT_TOKEN)}, got {cls.entry_defect!r}"
        )
        cls.flash_image = ted.ENCRYPTED_IMAGE if cls.encrypted else ted.PLAINTEXT_IMAGE
        cls.efuse_preload = ted.ENCRYPTED_EFUSE if cls.encrypted else ted.PLAINTEXT_EFUSE
        cls.primary_expected_error = ted.EXPECTED_ERROR[cls.entry_defect]
        cls.backup_sealed_check_toc = not cls.encrypted

        # The backup completes the whole positive chain, so the run is a real boot
        # and not an early exit that happened not to fail. The token names the arm
        # AND the entry index it fired on.
        required = [ted.DEFECT_TOKEN[cls.entry_defect],
                    "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Neither the sibling entry arm, nor either TOC-header arm, nor any
        # neighbouring structural one may be what fired, and the accepted backup
        # emits no MANIFEST_ERR= of its own, so every other code is forbidden.
        forbidden = ted.neighbouring_errors(cls.entry_defect)
        forbidden += ["CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        forbidden += list(ted.other_payload_tokens(cls.entry_defect))
        forbidden += list(ted.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [ted.DECRYPT_START, ted.DECRYPT_OK]
        else:
            # Positive evidence that this row ran the plaintext arm: the ROM calls
            # decrypt_payload() only for a slot whose encrypted_payload flag is
            # set, so the marker's absence is the flag's absence.
            forbidden.append(ted.DECRYPT_START)
        cls.extra_required = tuple(required)
        cls.extra_forbidden = tuple(forbidden)

    # --- stimulus ----------------------------------------------------------
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Which image was loaded is a property of the artefact, not of the member's
        # class attribute. Assert it, so a member that named the wrong image fails
        # here instead of quietly running the other cell's scenario.
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
        # The checks AHEAD of validate_manifest_payload must all be satisfiable, or
        # one of them produces the verdict and the arm under test never runs.
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

        # CHK-ENTRY-ATTRIBUTION: the arm's own token and the arm's error code are
        # BOTH the primary's, in that order, inside the primary's attempt. The token
        # carries the entry index, so this says which rule fired and on which TOC
        # entry; the error code says what the ROM returned. Exactly one occurrence,
        # because a second would mean the backup carried the same defect -- which is
        # the terminal scenario rather than this one.
        n = fd.count(console, token)
        assert n == 1, (
            f"{token} appeared {n} times, expected exactly 1 (the primary's). "
            f"Console: {console}"
        )
        i_token = fd.assert_slot_attributed(console, token, after=i_psrc,
                                            before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_token,
                                          before=i_bsrc)

        # CHK-DECRYPT-ARM: an encrypted member must show BOTH slots decrypting, with
        # the primary's own pair inside its attempt and ordered
        # DECRYPT_START -> DECRYPT_OK -> token. That order is what places the entry
        # rejection after a SUCCESSFUL decryption rather than in place of one.
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

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes at
        # this row's field address. The sibling arm mutates a DIFFERENT TOC-entry
        # field, so a run that planted it would fail here even if the console had
        # somehow agreed.
        ted.assert_served_entry_field(self.logger, flash, "primary",
                                      self.entry_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-ENTRY-RULE: primary@%d violated %s, was announced %s@%d and "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, self.entry_defect, token, i_token, slot_err, i_err, i_bsrc,
        )
