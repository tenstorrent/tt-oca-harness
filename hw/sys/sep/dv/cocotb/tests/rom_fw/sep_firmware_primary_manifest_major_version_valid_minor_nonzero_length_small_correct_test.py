# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with a length inside the range rule; it boots.

The primary-side ``minor != 0`` ACCEPTED case: the primary is accepted, the boot
completes from it, and the backup slot is never read.

THE RULE, from ``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``)::

    minor == 0  ->  manifest_length == sizeof(manifest_t)   EXACTLY
    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

The stimulus is minor 1 with ``sizeof(manifest_t) + 4`` = 1188, 4-byte aligned and
strictly inside the range.

============================================================================
WHY THIS IS THE ROW THAT PROVES THE ARM WAS TAKEN
============================================================================

1188 at minor 0 is REFUSED -- that is
``sep_firmware_primary_manifest_major_version_valid_minor_0_length_incorrect_test``,
which plants the identical length in the identical slot. The two rows differ in one
16-bit field, ``manifest_version_minor``, and the outcome inverts from a failover
to a primary boot. Neither checker can pass on the other's log: that one requires a
backup read and a primary ``MANIFEST_ERR=0x00030004``, this one forbids both.

1185 at minor 1 is also REFUSED -- that is
``..._minor_nonzero_length_small_incorrect_test``, which plants the same minor in
the same slot four bytes below this one. The two differ only in the low two bits of
``manifest_length``, and the outcome inverts from a primary boot to a failover, so
the pair is the ALIGNMENT discriminator.

**THE RANGE RULE'S LOWER BOUND IS NOT BRACKETED BY ANY ROW.** No row in this group
declares a ``manifest_length`` below ``sizeof(manifest_t)`` at a non-zero minor, so
nothing here shows the lower bound rejecting. A ROM that dropped that bound
entirely -- accepting any aligned v1.x length up to ``MANIFEST_MAX_SIZE`` -- would
pass every row in this group. Closing it needs a ``minor != 0`` row below 1184,
which is not one of the approved matrix rows; it is recorded as a coverage gap
rather than invented here. (``sep_firmware_backup_manifest_identifier_test`` does
plant 1180, but at minor 0, so its verdict belongs to the exact-match arm.)

**THE ROM MAKES A SECOND, DIRECTLY OBSERVABLE DECISION ON THIS PATH.**
``load_manifest_extra`` (``manifest_load.c``) returns immediately when
``manifest_length <= sizeof(manifest_t)`` and otherwise fetches the difference from
the source. With 1188 that is a SEPARATE 4-byte flash read at
``primary_base + 1184``, issued after the 1184-byte header read and before the
payload load. Every other primary slot in this testlist declares exactly 1184 and
skips the call, so this transaction exists in this run and in no other primary-side
one. :meth:`check_transport` requires it from the BFM's own record -- the channel
the ROM cannot fake, since ``load_manifest_extra`` prints nothing -- which turns
"the ROM accepted a v1.1 manifest" into "the ROM accepted it AND acted on the
declared length". Its negative counterpart is
``..._minor_0_length_correct_test``, where 1184 must produce no such read.

The fetch is identified by the address the ROM COMMANDED, not by the span the BFM
recorded: ``ocah_spi_flash._do_read`` streams until CS deasserts, so the 1184-byte
header read is logged as 1185 bytes and its span already COVERS this address. Only
the start address separates the two.

============================================================================
WHY THE PRIMARY IS RE-SEALED
============================================================================

``manifest_version_minor`` and ``manifest_length`` both live INSIDE the TBS
(``manifest.h``), so mutating them invalidates ``manifest_hash`` and the signature.
Unlike every negative row in this group, this slot must SURVIVE the whole crypto
chain, so :func:`sep_payload_mutate.reseal` re-derives ``payload_hash``,
``manifest_hash`` and a genuine dev0 RSA-3072 signature over the modified TBS.
:func:`sep_payload_mutate.verify_signing_key` runs FIRST, on the untouched slot: it
proves the local signer reproduces the packer's shipped signature byte for byte, so
the re-seal is sound by construction rather than by hope. Without it a re-seal
failure would surface as the ROM rejecting the slot as ``SIG_FAILED`` -- which looks
exactly like a plausible negative result.

NO FAILOVER. The primary is valid, so a backup read would mean it was refused for a
reason this testcase does not model. The backup ``MANIFEST_SRC=`` is forbidden, and
:meth:`check_transport` additionally requires that the DEVICE served no read
covering the backup manifest address.

Needs ``+sep_crypto_edn_force``: the accepted primary runs a full RSA-3072 modexp on
OTBN.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR

# 4-byte aligned and strictly inside the range the minor != 0 arm accepts.
_PRIMARY_LENGTH = mm.MANIFEST_SIZE + 4
_PRIMARY_MINOR = 1

# load_manifest_extra(): the extra fetch this length forces, and its address.
_EXTRA_ADDR = mm.PRIMARY_MANIFEST_OFFSET + mm.MANIFEST_SIZE
_EXTRA_LEN = _PRIMARY_LENGTH - mm.MANIFEST_SIZE


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_small_correct_test(
        sep_rom_ot_secure_boot_test):
    """A v1.1/1188 primary is accepted, fetches its extension, and boots."""

    efuse_preload = _EFUSE_PRELOAD
    # The primary completes the whole positive chain, so the boot is a real one and
    # not an early exit that happened not to fail. The primary MANIFEST_SRC= is
    # already in the parent's required set.
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        "LC=PROD", "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    # No slot may be refused at all. "MANIFEST_ERR=" without a code forbids every
    # structural and cryptographic verdict in one line -- in particular every other
    # BAD_LENGTH arm, whose firing would mean the length this testcase declares
    # valid was refused for a reason it does not control.
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "MANIFEST_HASH_MISMATCH", "RSA_VERIFY_FAIL", "PLD_HASH_MISMATCH",
        "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
        "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE", "PAYLOAD_HASHED_LEN_BAD=",
        "PAYLOAD_LEN_RANGE", "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
        "PAYLOAD_LOC_OVERFLOW", "ENC_HASHED_LEN_PARTIAL",
        fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
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
            f"enforced, or the re-sealed slot would not be graded on a completed "
            f"crypto chain"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        fd.assert_clean_key_fuses(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x", lc, sboot_dis,
            image.field_int("BL1_VERSION"), image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        """Move the primary to v1.1/1188 and re-seal it into a bootable slot."""
        # Establish that the local signer reproduces the packer's own signature
        # BEFORE anything is modified, so the re-seal below is sound by construction.
        pm.verify_signing_key(buf, "primary")
        pm.verify_sealed(buf, "primary")
        # The range this stimulus must sit inside is a hand-copied mirror of a ROM
        # #define; require the two to still agree before relying on it.
        fd.assert_rom_manifest_bounds()

        before_ver = mm.manifest_version(buf, "primary")
        before_len = mm.manifest_length(buf, "primary")
        assert before_ver == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before_ver[0]}.{before_ver[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the baseline "
            f"this testcase moves away from"
        )
        assert before_len == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {before_len}, expected {mm.MANIFEST_SIZE}"
        )
        assert _PRIMARY_MINOR != 0, (
            "the minor version must be non-zero, or the exact-match arm applies and "
            "1188 would be REFUSED instead of accepted"
        )
        assert _PRIMARY_LENGTH % 4 == 0, (
            "the declared length is not 4-byte aligned, so the alignment check would "
            "refuse this slot regardless of the range rule"
        )
        assert mm.MANIFEST_SIZE <= _PRIMARY_LENGTH <= mm.MANIFEST_MAX_SIZE, (
            f"the declared length {_PRIMARY_LENGTH} is outside "
            f"[{mm.MANIFEST_SIZE}, {mm.MANIFEST_MAX_SIZE}], so the range rule would "
            f"refuse the slot this testcase requires it to accept"
        )
        assert _PRIMARY_LENGTH > mm.MANIFEST_SIZE, (
            f"the declared length {_PRIMARY_LENGTH} does not exceed "
            f"sizeof(manifest_t), so load_manifest_extra() would return without "
            f"reading and the extension fetch this testcase requires would not exist"
        )
        # validate_manifest_header also refuses payload_offset < manifest_length as
        # an overlap. The shipped payload_offset is well clear of 1188, but the
        # relation is what makes the acceptance possible, so it is asserted rather
        # than assumed.
        p_off = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        # Kept for check_transport(): the payload read is what the extension read
        # must precede, and its address is a property of the image.
        self._primary_payload_off = p_off
        assert p_off >= _PRIMARY_LENGTH, (
            f"primary payload_offset is {p_off}, below the declared manifest_length "
            f"{_PRIMARY_LENGTH}: the slot would be refused as "
            f"PAYLOAD_OVERLAPS_MANIFEST rather than accepted by the range rule"
        )

        mm.set_manifest_version(buf, "primary", minor=_PRIMARY_MINOR)
        mm.set_manifest_length(buf, "primary", _PRIMARY_LENGTH)
        pm.reseal(buf, "primary")

        after_ver = mm.manifest_version(buf, "primary")
        after_len = mm.manifest_length(buf, "primary")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _PRIMARY_MINOR), (
            f"primary manifest version is {after_ver[0]}.{after_ver[1]} after the "
            f"write, expected {mm.MANIFEST_MAJOR_VERSION}.{_PRIMARY_MINOR}"
        )
        assert after_len == _PRIMARY_LENGTH, (
            f"primary manifest_length is {after_len} after the write, expected "
            f"{_PRIMARY_LENGTH}"
        )
        # The re-seal has to be complete, or the ROM refuses the slot for a stale
        # hash or signature and the run proves nothing about the range rule.
        pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary %d.%d/%d -> %d.%d/%d and "
            "re-sealed. The minor is non-zero so the range rule is in force, and %d "
            "is aligned and inside [%d, %d]; payload_offset %d clears the declared "
            "length, so the slot must be ACCEPTED. It also exceeds "
            "sizeof(manifest_t) by %d, which forces load_manifest_extra() to fetch "
            "that many extra bytes",
            before_ver[0], before_ver[1], before_len,
            after_ver[0], after_ver[1], after_len, _PRIMARY_LENGTH,
            mm.MANIFEST_SIZE, mm.MANIFEST_MAX_SIZE, p_off, _EXTRA_LEN,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    def check_transport(self, console: list[str], flash) -> None:
        # CHK-STIMULUS-SERVED: the DUT-side stimulus half -- the device returned
        # 1.1 with length 1188, so the acceptance below is of the values this
        # testcase is named for.
        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _PRIMARY_MINOR,
                        _PRIMARY_LENGTH),
            "primary manifest_version_major/minor + manifest_length",
        )

        # CHK-ONE-HASH: exactly one manifest hash verified, and it is the primary's.
        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"primary's). Console: {console}"
        )
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert 0 <= i_psrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the primary read@{i_psrc}: "
            f"the hash that verified is not the primary's. Console: {console}"
        )

        # CHK-MANIFEST-EXTENSION: the ROM ACTED on the declared length. This is the
        # decision no other primary-side row reaches, and the BFM's record is the
        # only channel that can see it.
        rds = ev.reads(flash.get_transactions())
        p_starts = fd.reads_starting_at(flash, mm.PRIMARY_MANIFEST_OFFSET)
        assert p_starts, (
            f"no SPI read began at the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}"
        )
        p_idx = p_starts[0]
        x_starts = fd.reads_starting_at(flash, _EXTRA_ADDR)
        assert x_starts, (
            f"no SPI read began at 0x{_EXTRA_ADDR:x}. The primary declares "
            f"manifest_length {_PRIMARY_LENGTH}, which is {_EXTRA_LEN} bytes past "
            f"sizeof(manifest_t), so load_manifest_extra() (manifest_load.c) must "
            f"have fetched them: the ROM accepted the v1.1 length without acting on "
            f"it. Transactions: "
            f"{ev.summarize(flash.get_transactions(), self._image_len)}"
        )
        # Exactly one. rom_manifest_boot calls load_manifest_extra once for the
        # accepted slot, so a second fetch would not be the call this testcase
        # claims.
        assert len(x_starts) == 1, (
            f"{len(x_starts)} reads began at 0x{_EXTRA_ADDR:x} (indices {x_starts}), "
            f"expected exactly 1: load_manifest_extra() runs once for the accepted "
            f"slot"
        )
        x_idx = x_starts[0]
        x_start, x_end = ev.read_span(rds[x_idx])
        assert x_idx > p_idx, (
            f"the fetch at 0x{_EXTRA_ADDR:x} is read[{x_idx}], not after the primary "
            f"header read[{p_idx}]: it is not the extension fetch"
        )
        assert x_end - x_start >= _EXTRA_LEN, (
            f"the extension read covers 0x{x_start:x}..0x{x_end:x}, under the "
            f"{_EXTRA_LEN} bytes manifest_length declares"
        )
        payload_addr = mm.PRIMARY_MANIFEST_OFFSET + self._primary_payload_off
        pl_hit = ev.covering_read(rds, payload_addr)
        assert pl_hit is not None, (
            f"no SPI read covered the primary payload at 0x{payload_addr:x}; the "
            f"boot could not have completed from this slot"
        )
        assert x_idx < pl_hit[0], (
            f"the extension read[{x_idx}] did not precede the payload read"
            f"[{pl_hit[0]}]: load_manifest_extra() is called before load_payload() "
            f"(manifest_load.c), so this ordering is not the ROM's"
        )

        # CHK-NO-FAILOVER-ADDR: the device was never asked for the backup slot.
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert b_hit is None, (
            f"read[{b_hit[0] if b_hit else '?'}] covered the backup manifest "
            f"address 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the ROM fell over to the "
            f"backup, so the primary was not accepted. Transactions: "
            f"{ev.summarize(flash.get_transactions(), self._image_len)}"
        )
        self.logger.info(
            "CHK-LENGTH-RULE: primary@%d declared v%d.%d with manifest_length %d, was "
            "accepted with the only MANIFEST_HASH_OK@%d, and the device then served "
            "read[%d] 0x%06x..0x%06x -- the load_manifest_extra() fetch the declared "
            "length forces -- before the payload read[%d]. No read covered the backup "
            "slot. The range rule is demonstrated as taken, not merely satisfied",
            i_psrc, mm.MANIFEST_MAJOR_VERSION, _PRIMARY_MINOR, _PRIMARY_LENGTH,
            i_hash, x_idx, x_start, x_end, pl_hit[0],
        )
