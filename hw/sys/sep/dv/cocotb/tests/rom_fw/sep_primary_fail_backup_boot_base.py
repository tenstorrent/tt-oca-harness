# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the PRIMARY slot is rejected and the BACKUP boots.

The mirror image of ``sep_backup_manifest_fail_base``. There the backup carries
the defect and the run is terminal; here the primary carries it, the ROM falls
over, and a valid backup completes the boot. Subclasses supply the primary defect
and the verdict it must produce.

WHY THE RECOVERY IS THE RESULT, NOT A SIDE EFFECT. ``manifest_crypto_validate`` is
called from inside the per-slot attempt, so a cryptographic rejection returns into
``rom_manifest_boot``'s retry loop rather than ending the boot
(``manifest_load.c``). The reference treats these primary-side rejections as
warnings and expects a completed boot from the backup, so a port that ended
terminally would be testing a different requirement.

A PRECONDITION THE ``SIG_VALID`` COUNT ENCODES. :meth:`check_transport` requires
``SIG_VALID`` exactly once, which assumes every member's PRIMARY is refused at or
before ``validate_signature`` -- the manifest magic, the signature type, the
signature value, the key selection, the key index, key revocation and the security
version all return before ``manifest_crypto.c`` prints it. A member whose primary
defect sits DOWNSTREAM of the signature -- a payload hash mismatch
(``manifest_crypto.c``), a decryption failure or a TOC error (``manifest_load.c``)
-- prints ``SIG_VALID``, so such a member must parameterise the count
the way ``primary_expected_rsa_starts`` is parameterised
(``primary_expected_sig_valids: int = 0`` and
``assert n_sig == 1 + primary_expected_sig_valids``) rather than relax it.

THE BACKUP MUST BE PROVABLY VALID, and this base asserts that rather than assuming
it. After the subclass has planted its primary defect, two checks run over the
backup:

  * :func:`sep_payload_mutate.verify_sealed` -- TOC magic, the TOC/manifest
    payload-length agreement, ``payload_hash``, every image digest,
    ``manifest_hash`` over the TBS, and an RSA verification of the shipped
    signature against the **dev0 modulus read from the signing-key PEM**
    (``sep_payload_mutate.py``); and
  * :func:`sep_manifest_mutate.verify_public_key` -- SHA-256 of the modulus the
    manifest actually CARRIES equals the ROM's compiled-in slot-0 digest.

The second is what makes the first mean what it appears to mean: together they
establish that the signature verifies against the same key the ROM will bind to.
Without them, "it recovered" could be satisfied by a run that recovered from
something else, and a stimulus that accidentally damaged the backup would show up
as a confusing terminal failure instead of a loud one here.

ORDERING IS THE SUBSTANCE. Presence of a marker says nothing about which slot
produced it, so :meth:`check_transport` asserts the full chain -- primary read,
primary verdict, primary error, backup read, signature verified, manifest
accepted -- and additionally that the primary's own console token appears exactly
once and that ``SIG_VALID`` appears exactly once, the backup's.

WHERE THE PRIMARY'S REJECTION SITS RELATIVE TO THE VERIFIER IS DECLARED, NOT
ASSUMED. Most defects ported onto this base are refused upstream of
``rsa_3072_verify`` (``manifest_crypto.c``), so the primary's modulus must
never reach the verifier; a member whose defect IS the signature value has to
reach it. ``primary_expected_rsa_starts`` makes each member state which of the two
it is, and :meth:`check_transport` then asserts that branch in full: with 0, the
first ``RSA_VERIFY_START`` must follow the backup read and the total must be 1;
with 1, the primary's own ``RSA_VERIFY_START`` must sit between the primary read
and the primary error and the total must be 2. Asserting only the consequence of a
branch is not the same as asserting which branch was taken, so both the count and
the position are pinned -- a member that silently changed which arm rejected it
would otherwise keep passing.

Slot identity is asserted on ``MANIFEST_SRC=`` and on the device's own transaction
addresses, never on the ``MANIFEST_PRIMARY`` / ``MANIFEST_BACKUP`` label: the ROM
derives the label from the retry counter but the offset from the (possibly
rotated) slot index (``manifest_load.c``), so under ``rotate_update``
the label and the slot disagree. The offset cannot lie.
"""

from __future__ import annotations

import os
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

# manifest.h
MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_SIG_FAILED = 0x0003_000C
MANIFEST_ERR_VERSION_ROLLBACK = 0x0003_0014

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_RSA_START = "RSA_VERIFY_START"  # manifest_crypto.c
_SIG_VALID = "SIG_VALID"  # manifest_crypto.c
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"  # manifest_crypto.c
_MANIFEST_OK = "MANIFEST_OK"
_LC_PROD = "LC=PROD"

# Must not appear: secure boot skipped (so the verdict under test never ran), or
# the run ending terminal instead of recovering.
_SBOOT_OFF = "SBOOT_OFF"
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"


class sep_primary_fail_backup_boot_base(sep_rom_ot_dma_boot_test):
    """Plant a defect in the primary, require a failover and a completed boot."""

    flash_image = SECURE_FLASH_IMAGE

    # --- subclass contract -------------------------------------------------
    # Console marker the primary's defect must produce, or "" when the primary
    # fails structurally and prints no dedicated token of its own.
    primary_defect_marker: str = ""
    # ROM error code the PRIMARY slot must be rejected with.
    primary_expected_error: int = 0
    # How many times the PRIMARY slot drives rsa_3072_verify. 0 for every defect
    # refused upstream of the verifier -- the default, so no existing member's
    # behaviour changes -- and 1 for a member whose defect is the signature value
    # itself. See the module docstring: this is a declaration of which arm rejects
    # the primary, and check_transport asserts it rather than tolerating either.
    primary_expected_rsa_starts: int = 0
    # Committed OTP preload this scenario needs.
    efuse_preload: Path | None = None
    # Extra markers that must not appear, on top of the shared list.
    extra_forbidden: tuple[str, ...] = ()
    # Extra markers that must appear, on top of the shared list.
    extra_required: tuple[str, ...] = ()

    def corrupt_primary(self, buf: bytearray) -> None:
        raise NotImplementedError

    def prepare_backup(self, buf: bytearray) -> None:
        """Hook for a scenario whose backup is part of the stimulus.

        Default is a no-op: the shipped backup is already valid and that is what
        most members want. Whatever this does, the backup is checked with
        ``verify_sealed`` afterwards, so a hook that broke the signature would
        fail here rather than in the middle of a confusing terminal run.
        """

    def check_efuse(self, image) -> None:
        """Subclass hook for the fuse preconditions its defect depends on."""

    # --- wiring ------------------------------------------------------------
    @classmethod
    def _markers(cls) -> tuple[tuple[str, ...], tuple[str, ...]]:
        slot_err = f"MANIFEST_ERR=0x{cls.primary_expected_error:08x}"
        crypto_fail = f"CRYPTO_FAIL=0x{cls.primary_expected_error:08x}"
        required = (
            _LC_PROD,
            _PRIMARY_SRC,
            slot_err,
            _BACKUP_SRC,
            _RSA_START,
            _SIG_VALID,
            _CRYPTO_OK,
            _MANIFEST_OK,
        )
        if cls.primary_defect_marker:
            required += (cls.primary_defect_marker, crypto_fail)
        return required, (_SBOOT_OFF, _ALL_FAILED, _SBOOT_DIS_FUSE)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        req, forb = self._markers()
        # Instance attributes, so the two tuples are assembled from this
        # subclass's own error code rather than shared class state.
        self.required_markers = (
            sep_rom_ot_dma_boot_test.required_markers + req + tuple(self.extra_required)
        )
        self.forbidden_markers = (
            sep_rom_ot_dma_boot_test.forbidden_markers + forb + tuple(self.extra_forbidden)
        )

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced or the verdict under test is never reached"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        self.check_efuse(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.corrupt_primary(buf)
        self.prepare_backup(buf)
        # The whole claim of this scenario is that a VALID slot recovered the
        # boot. verify_sealed reproduces the ROM's own structural and
        # cryptographic checks over the backup, so that claim is established
        # before the simulation rather than inferred from its outcome.
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self.logger.info("CHK-STIMULUS-BACKUP:  %s", mm.describe(buf, "backup"))
        self.logger.info(
            "CHK-STIMULUS-BACKUP-SEALED: backup passes payload_hash, every TOC "
            "image digest, manifest_hash over the TBS, and RSA verification of "
            "its shipped signature against the dev0 modulus; and the modulus it "
            "carries hashes to the ROM's compiled-in slot-0 digest -- it is a "
            "genuinely bootable slot"
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = index_of(_PRIMARY_SRC)
        i_perr = index_of(slot_err)
        i_bsrc = index_of(_BACKUP_SRC)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_MANIFEST_OK)

        # CHK-FAILOVER: the primary was read, rejected for the planted reason, and
        # only then was the backup read. Two markers in any order would also be
        # satisfied by a ROM that read the backup first, which is not a failover.
        assert i_psrc >= 0 < i_perr, (
            f"primary read ({_PRIMARY_SRC}@{i_psrc}) or its rejection "
            f"({slot_err}@{i_perr}) is missing. Console: {console}"
        )
        assert i_psrc < i_perr < i_bsrc, (
            f"the primary rejection is not attributable to the primary slot: "
            f"{_PRIMARY_SRC}@{i_psrc} -> {slot_err}@{i_perr} -> "
            f"{_BACKUP_SRC}@{i_bsrc}. Console: {console}"
        )

        # CHK-DEFECT-ATTRIBUTION: the primary's own console token sits between the
        # primary read and the primary error, and occurs exactly once. A second
        # occurrence would mean the backup carried the same defect, which is the
        # terminal scenario rather than this one.
        if self.primary_defect_marker:
            i_defect = index_of(self.primary_defect_marker)
            assert i_psrc < i_defect < i_perr, (
                f"{self.primary_defect_marker}@{i_defect} does not sit between the "
                f"primary read@{i_psrc} and the primary error@{i_perr}: it is not "
                f"the primary's verdict. Console: {console}"
            )
            n = sum(1 for line in console if self.primary_defect_marker in line)
            assert n == 1, (
                f"{self.primary_defect_marker} appeared {n} times, expected "
                f"exactly 1 (the primary's); the backup must not carry this "
                f"defect. Console: {console}"
            )

        # CHK-RSA-ARM: the member declared whether the PRIMARY reaches the
        # verifier, and both the count and the position of the primary's own
        # RSA_VERIFY_START are asserted from that declaration. Neither half alone
        # is enough: a count of 2 with both occurrences after the backup read
        # would not be a primary-side signature failure, and a correctly placed
        # occurrence with the wrong total would mean a slot this stimulus does not
        # account for also drove the verifier.
        n_rsa = sum(1 for line in console if _RSA_START in line)
        expected_rsa = 1 + self.primary_expected_rsa_starts
        assert n_rsa == expected_rsa, (
            f"{_RSA_START} appeared {n_rsa} times, expected exactly {expected_rsa} "
            f"(the backup's, plus {self.primary_expected_rsa_starts} declared for "
            f"the primary). Console: {console}"
        )
        if self.primary_expected_rsa_starts == 0:
            # The primary's defect is refused upstream of rsa_3072_verify
            # (manifest_crypto.c), so a modulus that reached the verifier
            # would mean the ROM took the checks in a different order than this
            # stimulus assumes. "Rejected eventually" is not the same result.
            assert i_rsa > i_bsrc, (
                f"{_RSA_START}@{i_rsa} appeared before the backup slot was read"
                f"@{i_bsrc}: the primary reached the RSA verifier, but this member "
                f"declares primary_expected_rsa_starts=0. Console: {console}"
            )
        else:
            # The defect IS the signature value, so the primary MUST reach the
            # verifier -- and its run has to sit inside the primary's own attempt.
            assert i_psrc < i_rsa < i_perr, (
                f"{_RSA_START}@{i_rsa} does not sit between the primary read"
                f"@{i_psrc} and the primary error@{i_perr}: the primary did not "
                f"drive the verifier, so its rejection is not a signature verdict. "
                f"Console: {console}"
            )

        # Exactly one slot's signature verified. SIG_VALID is printed only after
        # rsa_3072_verify returns 0 (manifest_crypto.c), so a second
        # occurrence would mean two slots were accepted in one run.
        n_sig = sum(1 for line in console if _SIG_VALID in line)
        assert n_sig == 1, (
            f"{_SIG_VALID} appeared {n_sig} times, expected exactly 1 (the "
            f"backup's). Console: {console}"
        )

        # CHK-RECOVERED: the boot came from the backup, and its signature really
        # verified. SIG_VALID is only printed after rsa_3072_verify returns 0
        # (manifest_crypto.c), so this is the crypto chain passing, not a
        # skipped one.
        assert i_bsrc < i_sig < i_ok, (
            f"the accepted manifest is not the backup's: {_BACKUP_SRC}@{i_bsrc} -> "
            f"{_SIG_VALID}@{i_sig} -> {_MANIFEST_OK}@{i_ok}. Console: {console}"
        )
        self.logger.info(
            "CHK-PRIMARY-FAILOVER: primary@%d -> %s@%d -> backup@%d -> "
            "RSA_VERIFY_START@%d -> SIG_VALID@%d -> MANIFEST_OK@%d",
            i_psrc,
            slot_err,
            i_perr,
            i_bsrc,
            i_rsa,
            i_sig,
            i_ok,
        )

        # --- device evidence -------------------------------------------------
        # The console says which address the ROM INTENDED to read. The BFM's
        # transaction record says which address the device actually served, and in
        # what order -- the half the ROM cannot fake.
        rds = ev.reads(flash.get_transactions())
        p_hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert p_hit is not None, (
            f"no SPI read covered 0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the primary "
            f"was never fetched, so the run did not fail over FROM it"
        )
        assert b_hit is not None, (
            f"no SPI read covered 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the boot did "
            f"not come from the backup address"
        )
        p_idx, _p_txn = p_hit
        b_idx, _b_txn = b_hit
        assert p_idx < b_idx, (
            f"device served the backup address (read[{b_idx}]) before the primary "
            f"(read[{p_idx}]): the transaction order is not a failover"
        )
        self.logger.info(
            "CHK-FAILOVER-ADDR: device served read[%d] 0x%06x first and read[%d] 0x%06x second",
            p_idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            b_idx,
            mm.BACKUP_MANIFEST_OFFSET,
        )
