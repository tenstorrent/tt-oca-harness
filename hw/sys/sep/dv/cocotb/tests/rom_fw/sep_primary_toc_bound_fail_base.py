# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY's TOC claims a bad length or places image 0 too low; the backup boots.

Four members: ``{payload_image_exceeds_bound, toc_payload_size_mismatch} x
{plaintext, encrypted}``. They share everything except which rule is violated and
which of the two shipped images is loaded, and the base asserts both of those rather
than letting a member declare them and go unchecked.

WHY THE PRIMARY REACHES THE VERIFIER HERE. ``validate_manifest_payload`` runs AFTER
``manifest_crypto_validate`` (``bootrom/prod/src/manifest_load.c`` states the
required order: security version -> signature -> payload hash over ciphertext ->
decrypt -> TOC, with the TOC last precisely because an encrypted payload's TOC is
itself ciphertext). The stimulus re-seals the slot, so the primary's signature is
genuine and verifies. Both ``primary_expected_rsa_starts`` and
``primary_expected_sig_valids`` are therefore 1, and the base's own checks then
require the primary's ``RSA_VERIFY_START`` and ``SIG_VALID`` to sit inside the
primary attempt -- positive evidence that the rejection is downstream of the whole
crypto chain rather than an early structural refusal wearing the right error code.
That matters most to the PLEN members, whose verdict is ``MANIFEST_ERR_BAD_LENGTH``,
a code ``validate_manifest_header`` can also return from far upstream: the required
crypto ordering is what proves this row's BAD_LENGTH came from the TOC agreement
check and not from the manifest length check.

WHY THE TOKEN IS DECLARED THROUGH ``extra_required`` RATHER THAN
``primary_defect_marker``. Both arms here DO print. But
``sep_primary_fail_backup_boot_base._markers`` couples ``primary_defect_marker`` to
a required ``CRYPTO_FAIL=`` line, and this family never produces one:
``manifest_load.c`` prints ``CRYPTO_FAIL=`` only when ``manifest_crypto_validate``
fails, and these rejections happen after it succeeds. So the token is required
through ``extra_required`` and attributed by :meth:`check_transport` below, which
places it inside the primary's own attempt -- the same claim
``primary_defect_marker`` would have made, without the marker that does not belong
to this arm.

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
from rom_fw import sep_toc_bound_defect as tbd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_bound_fail_base(sep_primary_fail_backup_boot_base):
    """Plant a TOC length or entry-0 bound defect in the primary; require a failover."""

    # --- member contract ---------------------------------------------------
    # tbd.BOUND or tbd.PLEN.
    bound_defect: str = ""
    # Whether this member's payload is encrypted. Decides the image, the fuse
    # preload and the decryption evidence; asserted against the image's own flag.
    encrypted: bool = False

    # See the module docstring: these arms print a token, but not the one the base's
    # marker machinery would pair with it.
    primary_defect_marker = ""
    # The primary's signature verifies and its payload decrypts; only the TOC is
    # refused.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    def __init_subclass__(cls, **kwargs) -> None:
        """Derive the image, the fuse preload and the marker lists from the cell.

        Done at class-definition time rather than per instance, so a member is one
        pair of declarations and the two attributes that decide the scenario cannot
        drift apart from the markers that grade it.
        """
        super().__init_subclass__(**kwargs)
        assert cls.bound_defect in tbd.DEFECT_TOKEN, (
            f"{cls.__name__} must declare bound_defect as one of "
            f"{list(tbd.DEFECT_TOKEN)}, got {cls.bound_defect!r}"
        )
        cls.flash_image = tbd.ENCRYPTED_IMAGE if cls.encrypted else tbd.PLAINTEXT_IMAGE
        cls.efuse_preload = tbd.ENCRYPTED_EFUSE if cls.encrypted else tbd.PLAINTEXT_EFUSE
        cls.primary_expected_error = tbd.EXPECTED_ERROR[cls.bound_defect]
        cls.backup_sealed_check_toc = not cls.encrypted

        # The backup completes the whole positive chain, so the run is a real boot
        # and not an early exit that happened not to fail.
        required = [tbd.DEFECT_TOKEN[cls.bound_defect],
                    "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP="]
        # Neither the sibling arm, nor either per-image arm of the entry family, nor
        # either TOC-header arm, nor any neighbouring structural one may be what
        # fired, and the accepted backup emits no MANIFEST_ERR= of its own, so every
        # code but this row's is forbidden.
        forbidden = tbd.neighbouring_errors(cls.bound_defect)
        forbidden += ["CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        forbidden += list(tbd.other_payload_tokens(cls.bound_defect))
        forbidden += list(tbd.DECRYPT_FAILURE_TOKENS)
        if cls.encrypted:
            required += [tbd.DECRYPT_START, tbd.DECRYPT_OK]
        else:
            # Positive evidence that this row ran the plaintext arm: the ROM calls
            # decrypt_payload() only for a slot whose encrypted_payload flag is
            # set, so the marker's absence is the flag's absence.
            forbidden.append(tbd.DECRYPT_START)
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
        # one of them produces the verdict and the arm under test never runs. The
        # manifest length assertion is load-bearing for the PLEN members in
        # particular: validate_manifest_header returns the SAME BAD_LENGTH code.
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: the slot would be "
            f"refused by validate_manifest_header before the TOC is ever parsed"
        )
        assert mm.manifest_length(buf, "primary") == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {mm.manifest_length(buf, 'primary')}, "
            f"expected {mm.MANIFEST_SIZE}: validate_manifest_header would return "
            f"BAD_LENGTH from a different check with the same code"
        )
        self._served = tbd.plant(self.logger, buf, "primary", self.bound_defect)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        token = tbd.DEFECT_TOKEN[self.bound_defect]
        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-BOUND-ATTRIBUTION: the arm's own token and the arm's error code are
        # BOTH the primary's, in that order, inside the primary's attempt. Exactly
        # one occurrence, because a second would mean the backup carried the same
        # defect -- which is the terminal scenario rather than this one.
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
        # DECRYPT_START -> DECRYPT_OK -> token. That order is what places the TOC
        # rejection after a SUCCESSFUL decryption rather than in place of one.
        if self.encrypted:
            for marker in (tbd.DECRYPT_START, tbd.DECRYPT_OK):
                k = fd.count(console, marker)
                assert k == 2, (
                    f"{marker} appeared {k} times, expected exactly 2 (the mutated "
                    f"primary's and the recovering backup's). Console: {console}"
                )
            i_ds = fd.first_index(console, tbd.DECRYPT_START)
            i_do = fd.first_index(console, tbd.DECRYPT_OK)
            assert i_psrc < i_ds < i_do < i_token, (
                f"expected primary read@{i_psrc} -> {tbd.DECRYPT_START}@{i_ds} -> "
                f"{tbd.DECRYPT_OK}@{i_do} -> {token}@{i_token}: the primary's TOC "
                f"was not refused after its own payload decrypted. "
                f"Console: {console}"
            )
            self.logger.info(
                "CHK-DECRYPT-ARM: primary@%d -> %s@%d -> %s@%d -> %s@%d, and both "
                "markers appear twice (primary and recovering backup)",
                i_psrc, tbd.DECRYPT_START, i_ds, tbd.DECRYPT_OK, i_do, token, i_token,
            )

        # CHK-STIMULUS-SERVED: the device really returned this row's planted bytes at
        # this row's field address, in this row's slot. The sibling arm mutates a
        # DIFFERENT field, so a run that planted it would fail here even if the
        # console had somehow agreed; and on the encrypted members the ADDRESS is
        # what separates the primary cell from the backup one, because the two slots'
        # ciphertexts agree this early in the CBC chain.
        tbd.assert_served_bound_field(self.logger, flash, "primary",
                                      self.bound_defect, self._served,
                                      self._payload_offset)

        self.logger.info(
            "CHK-TOC-BOUND-RULE: primary@%d violated %s, was announced %s@%d and "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, self.bound_defect, token, i_token, slot_err, i_err, i_bsrc,
        )
