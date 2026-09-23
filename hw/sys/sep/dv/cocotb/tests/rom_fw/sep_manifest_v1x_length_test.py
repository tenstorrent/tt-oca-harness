# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""v1.x ``manifest_length``: 2048 accepted, 2049 refused, in one run.

The v1.1 primary declares 2049 and must be refused; the re-sealed v1.1 backup declares
2048, must fetch its 864-byte manifest extension and boot. Needs ``+sep_crypto_edn_force``.
"""

from __future__ import annotations

import struct
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

MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_BAD_VERSION = 0x0003_0003
MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_MINOR = 1
_ACCEPTED_LENGTH = mm.MANIFEST_MAX_SIZE
# 2049 is also misaligned, so which BAD_LENGTH arm refuses it is not identified.
_REFUSED_LENGTH = mm.MANIFEST_MAX_SIZE + 1
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR

_BACKUP_EXTRA_ADDR = mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE
_BACKUP_EXTRA_LEN = _ACCEPTED_LENGTH - mm.MANIFEST_SIZE
_PRIMARY_EXTRA_ADDR = mm.PRIMARY_MANIFEST_OFFSET + mm.MANIFEST_SIZE


@pyuvm.test()
class sep_manifest_v1x_length_test(sep_primary_fail_backup_boot_base):
    """v1.1/2049 refused on the primary; v1.1/2048 accepted on the backup."""

    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = (f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}",
                       f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_VERSION:08x}",
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "PAYLOAD_LOC_OVERFLOW", "PAYLOAD_LOC_OT_OOB",
                       "ENC_HASHED_LEN_PARTIAL", "ENC_WITHOUT_SBOOT",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _assert_baseline(self, buf: bytes, slot: str) -> None:
        ver = mm.manifest_version(buf, slot)
        length = mm.manifest_length(buf, slot)
        assert ver == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"{slot} manifest version is {ver[0]}.{ver[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the baseline "
            f"this testcase moves away from"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"{slot} manifest_length is {length}, expected {mm.MANIFEST_SIZE}"
        )
        base = mm.slot_base(slot)
        assert bytes(buf[base:base + 4]) == mm.MANIFEST_MAGIC, (
            f"{slot} manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            f"the length check and the asserted code would be wrong"
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        rom_max = fd.assert_rom_manifest_bounds()
        assert rom_max == mm.MANIFEST_MAX_SIZE == 2048, (
            f"MANIFEST_MAX_SIZE is {rom_max}; TP078 names 2048 accepted and 2049 "
            f"refused, so a different bound makes both legs address the wrong values"
        )
        self._assert_baseline(buf, "primary")

        assert _MINOR != 0, (
            "the minor version must be non-zero, or the exact-match arm applies and "
            "the verdict would belong to the v1.0 rule instead of the v1.x one"
        )
        assert _REFUSED_LENGTH == mm.MANIFEST_MAX_SIZE + 1, (
            f"the refused length {_REFUSED_LENGTH} is not MANIFEST_MAX_SIZE + 1, so "
            f"it does not bracket the bound the accepted slot sits on"
        )
        assert _REFUSED_LENGTH > mm.MANIFEST_MAX_SIZE, (
            "derivation error: the refused length must exceed the range rule's "
            "upper bound"
        )
        assert _REFUSED_LENGTH % 4 != 0, (
            "derivation error: MANIFEST_MAX_SIZE + 1 cannot be 4-byte aligned"
        )
        assert _REFUSED_LENGTH > mm.MANIFEST_SIZE, (
            f"the refused length {_REFUSED_LENGTH} does not exceed "
            f"sizeof(manifest_t), so the absence of an extension fetch would be "
            f"evidence of nothing"
        )

        mm.set_manifest_version(buf, "primary", minor=_MINOR)
        mm.set_manifest_length(buf, "primary", _REFUSED_LENGTH)

        after_ver = mm.manifest_version(buf, "primary")
        after_len = mm.manifest_length(buf, "primary")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _MINOR), (
            f"primary version is {after_ver[0]}.{after_ver[1]} after the write, "
            f"expected {mm.MANIFEST_MAJOR_VERSION}.{_MINOR}; the mutation did not land"
        )
        assert after_len == _REFUSED_LENGTH, (
            f"primary manifest_length is {after_len} after the write, expected "
            f"{_REFUSED_LENGTH}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-LENGTH: primary %d.%d/%d -> %d.%d/%d. The major "
            "version is held VALID and the minor is non-zero, so the v1.0 "
            "exact-match arm is not in force; %d is MANIFEST_MAX_SIZE + 1 and is "
            "misaligned, so the range rule's upper bound and the 4-byte alignment "
            "rule BOTH refuse it and both return MANIFEST_ERR_BAD_LENGTH. Which of "
            "the two produced the verdict is not separable on this ROM and is not "
            "claimed",
            mm.MANIFEST_MAJOR_VERSION, 0, mm.MANIFEST_SIZE,
            after_ver[0], after_ver[1], after_len, _REFUSED_LENGTH,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        self._assert_baseline(buf, "backup")

        assert _ACCEPTED_LENGTH == mm.MANIFEST_MAX_SIZE, (
            f"the accepted length {_ACCEPTED_LENGTH} is not MANIFEST_MAX_SIZE, so "
            f"this row would not sit ON the bound and an off-by-one ROM could pass it"
        )
        assert _ACCEPTED_LENGTH % 4 == 0, (
            "derivation error: the accepted length must be 4-byte aligned, or the "
            "alignment rule would refuse the slot this row requires to boot"
        )
        assert mm.MANIFEST_SIZE <= _ACCEPTED_LENGTH, (
            "derivation error: the accepted length must satisfy the range rule's "
            "lower bound"
        )
        assert _ACCEPTED_LENGTH > mm.MANIFEST_SIZE, (
            f"the accepted length {_ACCEPTED_LENGTH} does not exceed "
            f"sizeof(manifest_t), so load_manifest_extra() would return without "
            f"reading and the acceptance would have no device-side half"
        )
        p_abs = pm.payload_base(buf, "backup")
        p_off = p_abs - mm.slot_base("backup")
        assert p_off >= _ACCEPTED_LENGTH, (
            f"backup payload_offset is {p_off}, below the declared manifest_length "
            f"{_ACCEPTED_LENGTH}: the slot would be refused as "
            f"PAYLOAD_OVERLAPS_MANIFEST rather than accepted by the range rule"
        )
        assert _BACKUP_EXTRA_ADDR + _BACKUP_EXTRA_LEN <= p_abs, (
            f"the {_BACKUP_EXTRA_LEN}-byte extension at "
            f"0x{_BACKUP_EXTRA_ADDR:x} runs into the backup payload at 0x{p_abs:x}"
        )
        assert _BACKUP_EXTRA_ADDR + _BACKUP_EXTRA_LEN <= len(buf), (
            f"the image is {len(buf)} bytes, short of the extension end "
            f"0x{_BACKUP_EXTRA_ADDR + _BACKUP_EXTRA_LEN:x}"
        )
        self._backup_payload_addr = p_abs
        extension = bytes(buf[_BACKUP_EXTRA_ADDR:
                              _BACKUP_EXTRA_ADDR + _BACKUP_EXTRA_LEN])

        mm.set_manifest_version(buf, "backup", minor=_MINOR)
        mm.set_manifest_length(buf, "backup", _ACCEPTED_LENGTH)
        pm.reseal(buf, "backup")

        after_ver = mm.manifest_version(buf, "backup")
        after_len = mm.manifest_length(buf, "backup")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _MINOR), (
            f"backup version is {after_ver[0]}.{after_ver[1]} after the write, "
            f"expected {mm.MANIFEST_MAJOR_VERSION}.{_MINOR}; the mutation did not land"
        )
        assert after_len == _ACCEPTED_LENGTH, (
            f"backup manifest_length is {after_len} after the write, expected "
            f"{_ACCEPTED_LENGTH}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-LENGTH: backup %d.%d/%d -> %d.%d/%d and re-sealed. "
            "The minor is non-zero so the range rule is in force, %d is aligned and "
            "equals MANIFEST_MAX_SIZE exactly, and payload_offset %d clears it, so "
            "the slot must be ACCEPTED. It exceeds sizeof(manifest_t) by %d, which "
            "forces load_manifest_extra() to fetch that many bytes at 0x%06x (the "
            "image holds %d bytes of 0x%02x there, clear of the payload at 0x%06x)",
            mm.MANIFEST_MAJOR_VERSION, 0, mm.MANIFEST_SIZE,
            after_ver[0], after_ver[1], after_len, _ACCEPTED_LENGTH, p_off,
            _BACKUP_EXTRA_LEN, _BACKUP_EXTRA_ADDR, len(extension),
            extension[0] if extension else 0, p_abs,
        )
        self.logger.info(
            "CHK-STIMULUS-BOUNDARY: both slots declare v%d.%d and differ by 1 in "
            "manifest_length -- primary %d, backup %d -- so the run brackets "
            "MANIFEST_MAX_SIZE from both sides under one supported minor version",
            mm.MANIFEST_MAJOR_VERSION, _MINOR, _REFUSED_LENGTH, _ACCEPTED_LENGTH,
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # Verify the signer on the untouched backup before the re-seal changes it.
        pm.verify_signing_key(buf, "backup")
        pm.verify_sealed(buf, "backup")
        return super().mutate_flash_image(buf)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # The length check precedes the hash, so the one MANIFEST_HASH_OK is the backup's.
        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so manifest_length {_REFUSED_LENGTH} was "
            f"accepted. Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )

        # No length arm prints a token, so check the bytes each slot was served.
        for slot, length in (("primary", _REFUSED_LENGTH),
                             ("backup", _ACCEPTED_LENGTH)):
            fd.assert_served_field(
                self.logger, flash, slot, _VERSION_LENGTH_OFF,
                struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _MINOR, length),
                f"{slot} manifest_version_major/minor + manifest_length",
            )

        fd.assert_no_read_starting_at(
            self.logger, flash, _PRIMARY_EXTRA_ADDR,
            f"the primary declares manifest_length {_REFUSED_LENGTH}, which exceeds "
            f"sizeof(manifest_t), so a fetch beginning there would mean "
            f"load_manifest_extra() ran and 2049 was accepted instead of refused as "
            f"BAD_LENGTH",
        )

        # Match by start address: the header read's recorded span already covers this one.
        rds = ev.reads(flash.get_transactions())
        b_starts = fd.reads_starting_at(flash, mm.BACKUP_MANIFEST_OFFSET)
        assert b_starts, (
            f"no SPI read began at the backup manifest address "
            f"0x{mm.BACKUP_MANIFEST_OFFSET:x}"
        )
        b_idx = b_starts[0]
        x_starts = fd.reads_starting_at(flash, _BACKUP_EXTRA_ADDR)
        assert x_starts, (
            f"no SPI read began at 0x{_BACKUP_EXTRA_ADDR:x}. The backup declares "
            f"manifest_length {_ACCEPTED_LENGTH}, which is {_BACKUP_EXTRA_LEN} bytes "
            f"past sizeof(manifest_t), so load_manifest_extra() (manifest_load.c) "
            f"must have fetched them: the ROM accepted a length of exactly "
            f"MANIFEST_MAX_SIZE without acting on it. Transactions: "
            f"{ev.summarize(flash.get_transactions(), self._image_len)}"
        )
        assert len(x_starts) == 1, (
            f"{len(x_starts)} reads began at 0x{_BACKUP_EXTRA_ADDR:x} (indices "
            f"{x_starts}), expected exactly 1: load_manifest_extra() runs once for "
            f"the accepted slot"
        )
        x_idx = x_starts[0]
        x_start, x_end = ev.read_span(rds[x_idx])
        assert x_idx > b_idx, (
            f"the fetch at 0x{_BACKUP_EXTRA_ADDR:x} is read[{x_idx}], not after the "
            f"backup header read[{b_idx}]: it is not the extension fetch"
        )
        assert x_end - x_start >= _BACKUP_EXTRA_LEN, (
            f"the extension read covers 0x{x_start:x}..0x{x_end:x}, under the "
            f"{_BACKUP_EXTRA_LEN} bytes manifest_length declares"
        )
        pl_hit = ev.covering_read(rds, self._backup_payload_addr)
        assert pl_hit is not None, (
            f"no SPI read covered the backup payload at "
            f"0x{self._backup_payload_addr:x}; the boot could not have completed "
            f"from this slot"
        )
        assert x_idx < pl_hit[0], (
            f"the extension read[{x_idx}] did not precede the payload read"
            f"[{pl_hit[0]}]: load_manifest_extra() is called before load_payload() "
            f"(manifest_load.c), so this ordering is not the ROM's"
        )
        self.logger.info(
            "CHK-V1X-LENGTH-BOUNDARY: the primary declared v%d.%d/%d and was refused "
            "MANIFEST_ERR=0x%08x inside its own attempt with no fetch at 0x%06x and "
            "no hash computed; the backup declared v%d.%d/%d -- one less, the same "
            "minor -- took the only MANIFEST_HASH_OK@%d, then the device served "
            "read[%d] 0x%06x..0x%06x, the load_manifest_extra() fetch that length "
            "forces, before the payload read[%d] and the boot completed. "
            "MANIFEST_MAX_SIZE is bracketed from both sides",
            mm.MANIFEST_MAJOR_VERSION, _MINOR, _REFUSED_LENGTH,
            self.primary_expected_error, _PRIMARY_EXTRA_ADDR,
            mm.MANIFEST_MAJOR_VERSION, _MINOR, _ACCEPTED_LENGTH, i_hash,
            x_idx, x_start, x_end, pl_hit[0],
        )
