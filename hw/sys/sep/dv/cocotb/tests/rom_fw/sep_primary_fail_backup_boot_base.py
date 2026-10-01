# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the PRIMARY slot is rejected and the BACKUP boots.

The mirror image of ``sep_backup_manifest_fail_base``. There the backup carries
the defect and the run is terminal; here the primary carries it, the ROM falls
over, and a valid backup completes the boot. Subclasses supply the primary defect
and the verdict it must produce.

WHY THE RECOVERY IS THE RESULT, NOT A SIDE EFFECT. Signature verification runs
inside the per-slot attempt, so a cryptographic rejection returns into
``rom_manifest_boot``'s retry loop rather than ending the boot (``oca_boot.c``,
and SEP-ROM-RETRY-030: the retry unit is the whole per-slot chain). These members
expect a completed boot from the backup, so a port that ended terminally would be
testing a different requirement.

A PRECONDITION THE ``RSA_VERIFY_OK`` COUNT ENCODES, AND WHICH IS NOT PARAMETERISED.
:meth:`check_transport` requires ``RSA_VERIFY_OK`` exactly once, which silently
assumes that every member's PRIMARY is refused at or before signature
verification. That holds for all members today -- their defects are the manifest
magic, the signature type, the signature value, the key selection, the key index,
key revocation and the security version, all of which return before the verifier
runs. It would NOT hold for a member whose primary defect sits DOWNSTREAM of the
signature: a payload hash mismatch, a decryption failure or a TOC error. Such a
primary legitimately prints ``RSA_VERIFY_OK``,
the count becomes 2, and this base would fail it for the wrong reason.

That shape arrived on 2026-09-15 with ``sep_decryption_failure_failover_test``,
whose primary decrypts successfully and is then refused on the TOC identifier --
precisely the "TOC error" case named above. So the count is now parameterised as
this note prescribed, by ``primary_expected_rsa_oks``, rather than relaxed. The
default is 0, which is the previous behaviour exactly, so the nine members that
predate it keep their evidence unchanged and none of their assertions move.

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
once and that ``RSA_VERIFY_OK`` appears exactly once, the backup's.

WHERE THE PRIMARY'S REJECTION SITS RELATIVE TO THE VERIFIER IS DECLARED, NOT
ASSUMED. Most defects ported onto this base are refused upstream of
the RSA verifier (``rsa_verify.c``), so the primary's modulus must
never reach the verifier; a member whose defect IS the signature value has to
reach it. ``primary_expected_rsa_starts`` makes each member state which of the two
it is, and :meth:`check_transport` then asserts that branch in full: with 0, the
first ``RSA_EXEC`` must follow the backup read and the total must be 1;
with 1, the primary's own ``RSA_EXEC`` must sit between the primary read
and the primary error and the total must be 2. Asserting only the consequence of a
branch is not the same as asserting which branch was taken, so both the count and
the position are pinned -- a member that silently changed which arm rejected it
would otherwise keep passing.

Slot identity is asserted on ``MANIFEST_SRC=`` and on the device's own transaction
addresses rather than on the ``MANIFEST_PRIMARY`` / ``MANIFEST_BACKUP`` label.
The ROM now derives both from the slot index (``oca_boot.c``), so under
``rotate_update`` the label and the offset agree -- but the offset is the device's
own statement of what it read, so it stays the evidence.
"""

from __future__ import annotations

import os
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

# Rejection codes the ROM prints as MANIFEST_ERR=<code>, derived from the
# validator's result enum rather than copied: the enum renumbers as the library
# grows, and a stale value fails a test for the wrong reason while still reading
# as the planted defect.
MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
MANIFEST_ERR_SIG_FAILED = mm.boot_err("OCA_FAIL_SIGNATURE")
MANIFEST_ERR_VERSION_ROLLBACK = mm.boot_err("OCA_FAIL_SECURITY_VERSION")
# Every refusal from plat_is_key_authorized() carries this one code -- slot
# reserved, selector ambiguous or empty, slot unprovisioned, algorithm or encoding
# unsupported, digest mismatch. The code means "this key is not authorized"; the
# console marker beside it is what says which arm refused, so a member pins the
# code here and the reason through its defect marker.
MANIFEST_ERR_KEY_UNAUTHORIZED = mm.boot_err("OCA_FAIL_ROOT_KEY_UNAUTHORIZED")
# A signature/public-key size or algorithm field that disagrees with itself is
# refused structurally, before key selection runs, so this arm prints no PUBK_*
# marker at all.
MANIFEST_ERR_SIG_TYPE_INVALID = mm.boot_err("OCA_FAIL_CRYPTO_FIELD_SIZE")

_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
# rsa_verify.c. "The slot was accepted" is what MANIFEST_OK says, and it is
# already required below, so there is no separate marker for it.
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"
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
    # How many times the PRIMARY slot drives the RSA verifier. 0 for every defect
    # refused upstream of the verifier -- the default, so no existing member's
    # behaviour changes -- and 1 for a member whose defect is the signature value
    # itself. See the module docstring: this is a declaration of which arm rejects
    # the primary, and check_transport asserts it rather than tolerating either.
    primary_expected_rsa_starts: int = 0
    # How many times the PRIMARY slot's signature VERIFIES. 0 for a primary refused
    # at or before the verifier -- the default, and true of every member that
    # predates this -- and 1 for a primary whose defect sits DOWNSTREAM of the
    # signature, which therefore prints RSA_VERIFY_OK of its own. Declaring it is
    # what separates "two slots verified because this defect is downstream" from
    # "two slots were accepted in one run", which would be a real ROM defect.
    primary_expected_rsa_oks: int = 0
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
        # Every per-slot rejection is reported as MANIFEST_ERR=<code>
        # (oca_boot.c), so the code is what attributes the refusal.
        slot_err = f"MANIFEST_ERR=0x{cls.primary_expected_error:08x}"
        required = (
            _LC_PROD,
            _PRIMARY_SRC,
            slot_err,
            _BACKUP_SRC,
            _RSA_EXEC,
            _RSA_OK,
            _MANIFEST_OK,
        )
        if cls.primary_defect_marker:
            required += (cls.primary_defect_marker,)
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

        def index_after(marker: str, after: int) -> int:
            """First occurrence of ``marker`` strictly after line ``after``.

            The accepted-manifest checks below want the BACKUP's markers. Taking
            the first occurrence overall is only unambiguous while the primary
            prints neither, which is true of every member whose primary is refused
            at or before signature verification -- for those this returns exactly
            what index_of() did. A member declaring
            ``primary_expected_rsa_oks`` has a primary that prints RSA_VERIFY_OK
            and MANIFEST_OK of its own, and for those the first occurrence is the
            PRIMARY's, which made the ordering assertion compare the wrong lines.
            """
            if after < 0:
                return -1
            for i in range(after + 1, len(console)):
                if marker in console[i]:
                    return i
            return -1

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = index_of(_PRIMARY_SRC)
        i_perr = index_of(slot_err)
        i_bsrc = index_of(_BACKUP_SRC)
        i_rsa = index_of(_RSA_EXEC)
        # The BACKUP's, not the run's first -- see index_after().
        i_sig = index_after(_RSA_OK, i_bsrc)
        i_ok = index_after(_MANIFEST_OK, i_bsrc)

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
        #
        # The upper bound is inclusive because a member whose defect IS its error
        # code -- one with a dedicated MANIFEST_ERR rather than a shared one, which
        # declares that code as its defect marker -- puts the two on the same console
        # line. A distinct token cannot share a line with the error, so allowing
        # equality only admits that degenerate case and still pins the ordering
        # against the read and, through slot_err above, against the backup read.
        if self.primary_defect_marker:
            i_defect = index_of(self.primary_defect_marker)
            assert i_psrc < i_defect <= i_perr, (
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
        # RSA_EXEC occurrences are asserted from that declaration. Neither half alone
        # is enough: a count of 2 with both occurrences after the backup read
        # would not be a primary-side signature failure, and a correctly placed
        # occurrence with the wrong total would mean a slot this stimulus does not
        # account for also drove the verifier.
        n_rsa = sum(1 for line in console if _RSA_EXEC in line)
        expected_rsa = 1 + self.primary_expected_rsa_starts
        assert n_rsa == expected_rsa, (
            f"{_RSA_EXEC} appeared {n_rsa} times, expected exactly {expected_rsa} "
            f"(the backup's, plus {self.primary_expected_rsa_starts} declared for "
            f"the primary). Console: {console}"
        )
        if self.primary_expected_rsa_starts == 0:
            # The primary's defect is refused upstream of the RSA verifier
            # (rsa_verify.c), so a modulus that reached the verifier
            # would mean the ROM took the checks in a different order than this
            # stimulus assumes. "Rejected eventually" is not the same result.
            assert i_rsa > i_bsrc, (
                f"{_RSA_EXEC}@{i_rsa} appeared before the backup slot was read"
                f"@{i_bsrc}: the primary reached the RSA verifier, but this member "
                f"declares primary_expected_rsa_starts=0. Console: {console}"
            )
        else:
            # The defect IS the signature value, so the primary MUST reach the
            # verifier -- and its run has to sit inside the primary's own attempt.
            assert i_psrc < i_rsa < i_perr, (
                f"{_RSA_EXEC}@{i_rsa} does not sit between the primary read"
                f"@{i_psrc} and the primary error@{i_perr}: the primary did not "
                f"drive the verifier, so its rejection is not a signature verdict. "
                f"Console: {console}"
            )

        # The backup's signature verified, plus however many the member declared
        # for its primary. RSA_VERIFY_OK is printed only after the verifier
        # returns success (rsa_verify.c:179), so an UNDECLARED second occurrence
        # would mean two slots were accepted in one run -- which is why this is a
        # declaration rather than a relaxation.
        n_sig = sum(1 for line in console if _RSA_OK in line)
        want_sig = 1 + self.primary_expected_rsa_oks
        assert n_sig == want_sig, (
            f"{_RSA_OK} appeared {n_sig} times, expected exactly {want_sig} (the "
            f"backup's, plus {self.primary_expected_rsa_oks} declared for the "
            f"primary). Console: {console}"
        )

        # CHK-RECOVERED: the boot came from the backup, and its signature really
        # verified. RSA_VERIFY_OK is only printed after the verifier returns
        # success (rsa_verify.c:179), so this is the crypto chain passing, not a
        # skipped one.
        assert i_bsrc < i_sig < i_ok, (
            f"the accepted manifest is not the backup's: {_BACKUP_SRC}@{i_bsrc} -> "
            f"{_RSA_OK}@{i_sig} -> {_MANIFEST_OK}@{i_ok}. Console: {console}"
        )
        self.logger.info(
            "CHK-PRIMARY-FAILOVER: primary@%d -> %s@%d -> backup@%d -> "
            "RSA_EXEC@%d -> RSA_VERIFY_OK@%d -> MANIFEST_OK@%d",
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
