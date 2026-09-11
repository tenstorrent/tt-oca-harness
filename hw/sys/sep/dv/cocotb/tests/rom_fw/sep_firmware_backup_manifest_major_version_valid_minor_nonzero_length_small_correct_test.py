# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with a length inside the range rule; it boots.

the ``minor != 0`` arm's ACCEPTED case: the backup is accepted and the boot
completes from it.

THE RULE, from ``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``)::

    minor == 0  ->  manifest_length == sizeof(manifest_t)   EXACTLY
    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

The stimulus is minor 1 with ``sizeof(manifest_t) + 4`` = 1188,
4-byte aligned and strictly inside the range.

============================================================================
WHY THIS IS THE ONLY MEMBER OF THE GROUP THAT PROVES THE ARM WAS TAKEN
============================================================================

1188 at minor 0 is REFUSED -- that is
``sep_firmware_backup_manifest_major_version_valid_minor_0_length_incorrect_test``,
which plants the identical length in the identical slot. The two rows differ in one
16-bit field, ``manifest_version_minor``, and the outcome inverts from a terminal
halt to a completed boot. Neither checker can pass on the other's log: that one
requires ``MANIFEST_ALL_FAILED`` and forbids every boot-progress marker, this one
requires ``MANIFEST_OK``, ``SIG_VALID`` and ``BL1_JUMP=``. **That pair is the
minor-version discriminator, and it is what makes the range rule falsifiable rather
than merely satisfied.**

**THE ROM MAKES A SECOND, DIRECTLY OBSERVABLE DECISION ON THIS PATH, AND NO OTHER
TESTCASE IN THIS DIRECTORY REACHES IT.** ``load_manifest_extra``
(``manifest_load.c``) fetches ``manifest_length - sizeof(manifest_t)`` extra bytes
whenever the declared length exceeds the header, on the accepted slot only. With
1188 that is a SEPARATE 4-byte flash read at ``backup_base + 1184``, issued after
the 1184-byte header read and before the payload load. Every other slot in this
testlist declares exactly 1184 and skips the call entirely, so this transaction
exists in this run and in no other. :meth:`check_transport` requires it from the
BFM's own record -- the channel the ROM cannot fake -- which turns "the ROM accepted
a v1.1 manifest" into "the ROM accepted it AND acted on the declared length".

============================================================================
THE FAILOVER TRIGGER, AND WHY THE BACKUP IS RE-SEALED
============================================================================

The trigger is the primary's ``manifest_identifier``, refused
as ``MANIFEST_ERR_BAD_MAGIC`` by the check immediately ahead of the version and
length ones, so it costs no hash or crypto work and cannot interact with the rule
under test.

``manifest_version_minor`` and ``manifest_length`` both live INSIDE the TBS
(``manifest.h``), so mutating them invalidates ``manifest_hash`` and the signature.
Unlike every negative member of this group, this slot must SURVIVE the whole crypto
chain, so :func:`sep_payload_mutate.reseal` re-derives ``payload_hash``,
``manifest_hash`` and a genuine dev0 RSA-3072 signature over the modified TBS.
:func:`sep_payload_mutate.verify_signing_key` runs FIRST, on the untouched slot: it
proves the local signer reproduces the packer's shipped signature byte for byte, so
the re-seal is sound by construction rather than by hope. Without it a re-seal
failure would surface as the ROM rejecting the slot as ``SIG_FAILED`` -- which looks
exactly like a plausible negative result.

MARKER SUBSTITUTION. ``SEP_MSG_INVALID_MANIFEST_ID`` is defined and never emitted,
so the primary's ``MANIFEST_ERR=0x00030002`` plus its position and count inside
the primary's own attempt carry that attribution instead.

Needs ``+sep_crypto_edn_force``: the recovering backup runs a full RSA-3072 modexp
on OTBN.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002

# 4-byte aligned and strictly inside the range the
# minor != 0 arm accepts.
_BACKUP_LENGTH = mm.MANIFEST_SIZE + 4
_BACKUP_MINOR = 1

# manifest_load.c load_manifest_extra(): the extra fetch this length forces, and
# the address it must come from.
_EXTRA_ADDR = mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE
_EXTRA_LEN = _BACKUP_LENGTH - mm.MANIFEST_SIZE


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_small_correct_test(
        sep_primary_fail_backup_boot_base):
    """Primary refused as BAD_MAGIC; a v1.1/1188 backup is accepted and boots."""

    # BAD_MAGIC prints no token of its own, so check_transport() below and the
    # base's error-code position and count carry the primary's attribution.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    # The backup completes the whole positive chain, so the boot is a real one and
    # not an early exit that happened not to fail.
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused inside validate_manifest_header, before the hash check
    # and before the crypto chain, and nothing may reject the backup -- in
    # particular none of the other BAD_LENGTH arms, whose tokens would mean the
    # length this testcase declares valid was refused for a reason it does not
    # control.
    extra_forbidden = ("MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "PAYLOAD_LOC_OVERFLOW", "ENC_HASHED_LEN_PARTIAL",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.set_identifier(buf, "primary")
        got = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert got != mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is still TBL1; the failover trigger did not "
            "land and the backup would never be reached"
        )
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-MAGIC: primary manifest_identifier -> %r, refused "
            "as MANIFEST_ERR=0x%08x by the check immediately ahead of the version "
            "and length rules -- the reference's own failover trigger",
            got, _MANIFEST_ERR_BAD_MAGIC,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        """Move the backup to v1.1/1188 and re-seal it into a genuinely bootable slot."""
        # Establish that the local signer reproduces the packer's own signature
        # BEFORE anything is modified, so the re-seal below is sound by construction.
        pm.verify_signing_key(buf, "backup")
        pm.verify_sealed(buf, "backup")
        # The range this stimulus must sit inside is a hand-copied mirror of a ROM
        # #define; require the two to still agree before relying on it.
        fd.assert_rom_manifest_bounds()

        before_ver = mm.manifest_version(buf, "backup")
        before_len = mm.manifest_length(buf, "backup")
        assert before_ver == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {before_ver[0]}.{before_ver[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the baseline "
            f"this testcase moves away from"
        )
        assert before_len == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {before_len}, expected {mm.MANIFEST_SIZE}"
        )
        assert _BACKUP_MINOR != 0, (
            "the minor version must be non-zero, or the exact-match arm applies and "
            "1188 would be REFUSED instead of accepted"
        )
        assert _BACKUP_LENGTH % 4 == 0, (
            "the declared length is not 4-byte aligned, so the alignment check would "
            "refuse this slot regardless of the range rule"
        )
        assert mm.MANIFEST_SIZE <= _BACKUP_LENGTH <= mm.MANIFEST_MAX_SIZE, (
            f"the declared length {_BACKUP_LENGTH} is outside "
            f"[{mm.MANIFEST_SIZE}, {mm.MANIFEST_MAX_SIZE}], so the range rule would "
            f"refuse the slot this testcase requires it to accept"
        )
        # validate_manifest_header also refuses payload_offset < manifest_length as
        # an overlap. The shipped payload_offset is well clear of 1188, but the
        # relation is what makes the acceptance possible, so it is asserted rather
        # than assumed.
        p_off = pm.payload_base(buf, "backup") - mm.slot_base("backup")
        # Kept for check_transport(): the payload read is what the extension read must
        # precede, and its address is a property of the image rather than a constant.
        self._backup_payload_off = p_off
        assert p_off >= _BACKUP_LENGTH, (
            f"backup payload_offset is {p_off}, below the declared manifest_length "
            f"{_BACKUP_LENGTH}: the slot would be refused as PAYLOAD_OVERLAPS_MANIFEST "
            f"rather than accepted by the range rule"
        )

        mm.set_manifest_version(buf, "backup", minor=_BACKUP_MINOR)
        mm.set_manifest_length(buf, "backup", _BACKUP_LENGTH)
        pm.reseal(buf, "backup")

        after_ver = mm.manifest_version(buf, "backup")
        after_len = mm.manifest_length(buf, "backup")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR), (
            f"backup manifest version is {after_ver[0]}.{after_ver[1]} after the "
            f"write, expected {mm.MANIFEST_MAJOR_VERSION}.{_BACKUP_MINOR}"
        )
        assert after_len == _BACKUP_LENGTH, (
            f"backup manifest_length is {after_len} after the write, expected "
            f"{_BACKUP_LENGTH}"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-VERSION: backup %d.%d/%d -> %d.%d/%d and re-sealed. "
            "The minor is non-zero so the range rule is in force, and %d is aligned "
            "and inside [%d, %d]; payload_offset %d clears the declared length, so "
            "the slot must be ACCEPTED. It also exceeds sizeof(manifest_t) by %d, "
            "which forces load_manifest_extra() to fetch that many extra bytes",
            before_ver[0], before_ver[1], before_len,
            after_ver[0], after_ver[1], after_len, _BACKUP_LENGTH,
            mm.MANIFEST_SIZE, mm.MANIFEST_MAX_SIZE, p_off, _EXTRA_LEN,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-MAGIC-ATTRIBUTION: BAD_MAGIC is the primary's and only the primary's.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASH-NOT-REACHED: the identifier check precedes manifest_check_integrity
        # (manifest_load.c), so the primary never had its hash computed and the single
        # MANIFEST_HASH_OK belongs to the accepted backup.
        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header. Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: the "
            f"one hash that verified is not the backup's. Console: {console}"
        )

        # CHK-MANIFEST-EXTENSION: the ROM ACTED on the declared length. This is the
        # decision no other testcase in this directory reaches, and the BFM's record
        # is the only channel that can see it -- load_manifest_extra() prints nothing.
        # The extension fetch is identified by the address the ROM COMMANDED, not by
        # the span the BFM recorded: ocah_spi_flash._do_read streams until CS
        # deasserts, so the 1184-byte header read is logged as 1185 bytes and its span
        # therefore COVERS this address. Only the start address separates the two.
        rds = ev.reads(flash.get_transactions())
        b_starts = fd.reads_starting_at(flash, mm.BACKUP_MANIFEST_OFFSET)
        assert b_starts, (
            f"no SPI read began at the backup manifest address "
            f"0x{mm.BACKUP_MANIFEST_OFFSET:x}"
        )
        b_idx = b_starts[0]
        x_starts = fd.reads_starting_at(flash, _EXTRA_ADDR)
        assert x_starts, (
            f"no SPI read began at 0x{_EXTRA_ADDR:x}. The backup declares "
            f"manifest_length {_BACKUP_LENGTH}, which is {_EXTRA_LEN} bytes past "
            f"sizeof(manifest_t), so load_manifest_extra() (manifest_load.c) must "
            f"have fetched them: the ROM accepted the v1.1 length without acting on "
            f"it. Transactions: {ev.summarize(flash.get_transactions(), self._image_len)}"
        )
        # Exactly one. rom_manifest_boot calls load_manifest_extra once for the
        # accepted slot, so a second fetch would not be the call this testcase claims.
        assert len(x_starts) == 1, (
            f"{len(x_starts)} reads began at 0x{_EXTRA_ADDR:x} (indices {x_starts}), "
            f"expected exactly 1: load_manifest_extra() runs once for the accepted slot"
        )
        x_idx = x_starts[0]
        x_start, x_end = ev.read_span(rds[x_idx])
        assert x_idx > b_idx, (
            f"the fetch at 0x{_EXTRA_ADDR:x} is read[{x_idx}], not after the backup "
            f"header read[{b_idx}]: it is not the extension fetch"
        )
        assert x_end - x_start >= _EXTRA_LEN, (
            f"the extension read covers 0x{x_start:x}..0x{x_end:x}, under the "
            f"{_EXTRA_LEN} bytes manifest_length declares"
        )
        payload_addr = mm.BACKUP_MANIFEST_OFFSET + self._backup_payload_off
        p_hit = ev.covering_read(rds, payload_addr)
        assert p_hit is not None, (
            f"no SPI read covered the backup payload at 0x{payload_addr:x}; the boot "
            f"could not have completed from this slot"
        )
        assert x_idx < p_hit[0], (
            f"the extension read[{x_idx}] did not precede the payload read"
            f"[{p_hit[0]}]: load_manifest_extra() is called before load_payload() "
            f"(manifest_load.c), so this ordering is not the ROM's"
        )
        self.logger.info(
            "CHK-LENGTH-RULE: primary@%d refused %s@%d before its hash was computed; "
            "backup@%d declared v%d.%d with manifest_length %d, was accepted with the "
            "only MANIFEST_HASH_OK@%d, and the device then served read[%d] "
            "0x%06x..0x%06x -- the load_manifest_extra() fetch the declared length "
            "forces. The range rule is demonstrated as taken, not merely satisfied",
            i_psrc, slot_err, i_err, i_bsrc, mm.MANIFEST_MAJOR_VERSION,
            _BACKUP_MINOR, _BACKUP_LENGTH, i_hash, x_idx, x_start, x_end,
        )
