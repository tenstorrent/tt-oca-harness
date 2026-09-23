# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares v1.1 with a length inside the range rule; it boots.

The primary is re-sealed at v1.1/1188 and the ROM must fetch its 4-byte extension.
Needs ``+sep_crypto_edn_force``: the accepted primary runs a full RSA-3072 modexp on OTBN.
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

_PRIMARY_LENGTH = mm.MANIFEST_SIZE + 4
_PRIMARY_MINOR = 1

# Match the read start, not its span: the flash model records one byte past each read.
_EXTRA_ADDR = mm.PRIMARY_MANIFEST_OFFSET + mm.MANIFEST_SIZE
_EXTRA_LEN = _PRIMARY_LENGTH - mm.MANIFEST_SIZE


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_nonzero_length_small_correct_test(
        sep_rom_ot_secure_boot_test):
    """A v1.1/1188 primary is accepted, fetches its extension, and boots."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        "LC=PROD", "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    # A bare "MANIFEST_ERR=" forbids every structural and cryptographic verdict.
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
        # A broken re-seal would look like a plausible SIG_FAILED, so prove the signer first.
        pm.verify_signing_key(buf, "primary")
        pm.verify_sealed(buf, "primary")
        # The manifest bounds mirror a ROM #define by hand; check they still agree.
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
        p_off = pm.payload_base(buf, "primary") - mm.slot_base("primary")
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
        # A stale hash or signature would refuse the slot for a reason unrelated to its length.
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
        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _PRIMARY_MINOR,
                        _PRIMARY_LENGTH),
            "primary manifest_version_major/minor + manifest_length",
        )

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
