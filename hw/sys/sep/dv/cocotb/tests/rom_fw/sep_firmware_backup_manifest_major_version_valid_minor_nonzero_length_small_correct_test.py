# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with a length inside the range rule; it boots.

The primary is refused as BAD_MAGIC; the backup moves to v1.1 with length 1188, is
re-sealed, and must fetch the 4 extra header bytes before it boots.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")

_BACKUP_LENGTH = mm.MANIFEST_SIZE + 4
_BACKUP_MINOR = 1

_EXTRA_ADDR = mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE
_EXTRA_LEN = _BACKUP_LENGTH - mm.MANIFEST_SIZE


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_small_correct_test(
    sep_primary_fail_backup_boot_base
):
    """Primary refused as BAD_MAGIC; a v1.1/1188 backup is accepted and boots."""

    # BAD_MAGIC prints no console token, so check_transport() carries the attribution.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = (
        "MANIFEST_HASH_MISMATCH",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "PLD_HASH_MISMATCH",
        "MANIFEST_ALL_FAILED",
        "IMAGE_HASH_MISMATCH",
        "NO_BL1_IMAGE",
        "PAYLOAD_OFF_ALIGN",
        "PAYLOAD_OFF_RANGE",
        "PAYLOAD_HASHED_LEN_BAD=",
        "PAYLOAD_LEN_RANGE",
        "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_PLEN_MISMATCH=",
        "PAYLOAD_LOC_OVERFLOW",
        "ENC_HASHED_LEN_PARTIAL",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.break_magic(buf, "primary")
        got = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert got != mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is still OCAC; the failover trigger did not "
            "land and the backup would never be reached"
        )
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-MAGIC: primary manifest_identifier -> %r, refused "
            "as MANIFEST_ERR=0x%08x by the check immediately ahead of the version "
            "and length rules -- the reference's own failover trigger",
            got,
            _MANIFEST_ERR_BAD_MAGIC,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        # minor and length sit inside the signed signed region, so the slot must be re-sealed to boot.
        # Check the signer first, or a bad re-seal looks like a genuine SIG_FAILED rejection.
        pm.verify_signing_key(buf, "backup")
        pm.verify_sealed(buf, "backup")
        # MANIFEST_MAX_SIZE is a hand-copied mirror of the ROM #define; check they still agree.
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
        p_off = pm.payload_base(buf, "backup") - mm.slot_base("backup")
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
            f"backup manifest_length is {after_len} after the write, expected {_BACKUP_LENGTH}"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-VERSION: backup %d.%d/%d -> %d.%d/%d and re-sealed. "
            "The minor is non-zero so the range rule is in force, and %d is aligned "
            "and inside [%d, %d]; payload_offset %d clears the declared length, so "
            "the slot must be ACCEPTED. It also exceeds sizeof(manifest_t) by %d, "
            "which forces load_manifest_extra() to fetch that many extra bytes",
            before_ver[0],
            before_ver[1],
            before_len,
            after_ver[0],
            after_ver[1],
            after_len,
            _BACKUP_LENGTH,
            mm.MANIFEST_SIZE,
            mm.MANIFEST_MAX_SIZE,
            p_off,
            _EXTRA_LEN,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

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

        # The SPI model records one extra byte per read, so match the extension by start address.
        rds = ev.reads(flash.get_transactions())
        b_starts = fd.reads_starting_at(flash, mm.BACKUP_MANIFEST_OFFSET)
        assert b_starts, (
            f"no SPI read began at the backup manifest address 0x{mm.BACKUP_MANIFEST_OFFSET:x}"
        )
        b_idx = b_starts[0]
        x_starts = fd.reads_starting_at(flash, _EXTRA_ADDR)
        assert x_starts, (
            f"no SPI read began at 0x{_EXTRA_ADDR:x}. The backup declares "
            f"manifest_length {_BACKUP_LENGTH}, which is {_EXTRA_LEN} bytes past "
            f"sizeof(manifest_t), so load_manifest_extra() (oca_boot.c) must "
            f"have fetched them: the ROM accepted the v1.1 length without acting on "
            f"it. Transactions: {ev.summarize(flash.get_transactions(), self._image_len)}"
        )
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
            f"(oca_boot.c), so this ordering is not the ROM's"
        )
        self.logger.info(
            "CHK-LENGTH-RULE: primary@%d refused %s@%d before its hash was computed; "
            "backup@%d declared v%d.%d with manifest_length %d, was accepted with the "
            "only MANIFEST_HASH_OK@%d, and the device then served read[%d] "
            "0x%06x..0x%06x -- the load_manifest_extra() fetch the declared length "
            "forces. The range rule is demonstrated as taken, not merely satisfied",
            i_psrc,
            slot_err,
            i_err,
            i_bsrc,
            mm.MANIFEST_MAJOR_VERSION,
            _BACKUP_MINOR,
            _BACKUP_LENGTH,
            i_hash,
            x_idx,
            x_start,
            x_end,
        )
