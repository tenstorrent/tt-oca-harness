# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY carries a silent TOC defect; the backup boots.

Four members: ``{version_major, image_count} x {plaintext, encrypted}``. They
share everything except which TOC field is planted and which of the two shipped
images is loaded, and the base asserts both of those rather than letting a member
declare them and go unchecked.

WHY THE PRIMARY REACHES THE VERIFIER HERE, unlike most members of
``sep_primary_fail_backup_boot_base``. ``validate_manifest_payload`` runs AFTER
``manifest_crypto_validate`` (``bootrom/prod/src/manifest_load.c`` states the
required order: security version -> signature -> payload hash over ciphertext ->
decrypt -> TOC, with the TOC last precisely because an encrypted payload's TOC is
itself ciphertext). The stimulus re-seals the slot, so the primary's signature is
genuine and verifies. Both ``primary_expected_rsa_starts`` and
``primary_expected_sig_valids`` are therefore 1, and the base's own checks then
require the primary's ``RSA_VERIFY_START`` and ``SIG_VALID`` to sit inside the
primary attempt -- which is positive evidence that the rejection is downstream of
the whole crypto chain rather than an early structural refusal wearing the right
error code.

WHAT SEPARATES THE ENCRYPTED MEMBERS FROM THE PLAINTEXT ONES, on the console
rather than by assertion. An encrypted member requires ``DECRYPT_START`` and
``DECRYPT_OK`` EXACTLY TWICE -- once for the mutated primary, once for the
recovering backup -- and requires the primary's pair to sit inside the primary
attempt. A plaintext member FORBIDS ``DECRYPT_START`` outright. So the two cells
cannot satisfy each other's checks, and neither can satisfy them by accident: the
image itself decides, and :meth:`mutate_flash_image` asserts the loaded image's
encryption flag matches what the member declares.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_fail_base(sep_primary_fail_backup_boot_base):
    """Plant a silent TOC defect in the primary, require a failover and a boot."""

    # --- member contract ---------------------------------------------------
    # "version_major" or "image_count".
    toc_field: str = ""
    # Whether this member's payload is encrypted. Decides the image, the fuse
    # preload and the decryption evidence; asserted against the image's own flag.
    encrypted: bool = False

    # The arm prints no token of its own, so the base's marker machinery is told
    # so explicitly rather than being handed an empty string by accident.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC is
    # refused. See the module docstring.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        """Derive the image, the fuse preload and the marker lists from the cell.

        Done at class-definition time rather than per instance, so a member is one
        pair of declarations and the two attributes that decide the scenario cannot
        drift apart from the markers that grade it.
        """
        super().__init_subclass__(**kwargs)
        assert cls.toc_field in td.FIELDS, (
            f"{cls.__name__} must declare toc_field as one of {list(td.FIELDS)}, "
            f"got {cls.toc_field!r}"
        )
        cls.flash_image = td.ENCRYPTED_IMAGE if cls.encrypted else td.PLAINTEXT_IMAGE
        cls.efuse_preload = td.ENCRYPTED_EFUSE if cls.encrypted else td.PLAINTEXT_EFUSE
        cls.primary_expected_error = td.EXPECTED_ERROR[cls.toc_field]
        cls.backup_sealed_check_toc = not cls.encrypted

        # The backup completes the whole positive chain, so the run is a real boot
        # and not an early exit that happened not to fail.
        required = ["MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Neither the sibling TOC arm nor any neighbouring one may be what fired,
        # and the accepted backup emits no MANIFEST_ERR= of its own, so every other
        # structural code is forbidden outright.
        forbidden = [f"MANIFEST_ERR=0x{td.sibling_error(cls.toc_field):08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_MAGIC:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_VERSION:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_LENGTH:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_BAD_TOC_ID:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_PAYLOAD_TOO_LARGE:08x}",
                     f"MANIFEST_ERR=0x{td.ERR_NO_BL1_IMAGE:08x}",
                     "CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        forbidden += list(td.OTHER_PAYLOAD_TOKENS) + list(td.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [td.DECRYPT_START, td.DECRYPT_OK]
        else:
            # Positive evidence that this row ran the plaintext arm: the ROM calls
            # decrypt_payload() only for a slot whose encrypted_payload flag is
            # set, so the marker's absence is the flag's absence.
            forbidden.append(td.DECRYPT_START)
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
        self._served = td.plant(self.logger, buf, "primary", self.toc_field)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-TOC-ATTRIBUTION: the planted arm's code is the primary's and only
        # the primary's. The arm is silent, so this code is the whole of the
        # ROM-side statement about WHICH check refused the slot -- which is why the
        # sibling arm's code and every neighbouring token are forbidden above.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-DECRYPT-ARM: an encrypted member must show BOTH slots decrypting,
        # with the primary's own pair inside its attempt and ordered
        # DECRYPT_START -> DECRYPT_OK -> rejection. That order is what places the
        # TOC rejection after a SUCCESSFUL decryption rather than in place of one.
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
                i_psrc, td.DECRYPT_START, i_ds, td.DECRYPT_OK, i_do, slot_err, i_err,
            )

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes
        # at this row's field address. The console cannot separate two cells that
        # share an error code; this can.
        td.assert_served_toc_field(self.logger, flash, "primary", self.toc_field,
                                   self._served, self._payload_offset)

        self.logger.info(
            "CHK-TOC-RULE: primary@%d declared TOC %s = %d and was refused %s@%d "
            "inside its own attempt, after its signature verified; the untouched "
            "backup was read@%d and booted",
            i_psrc, self.toc_field, td.PLANTED[self.toc_field], slot_err, i_err,
            i_bsrc,
        )
