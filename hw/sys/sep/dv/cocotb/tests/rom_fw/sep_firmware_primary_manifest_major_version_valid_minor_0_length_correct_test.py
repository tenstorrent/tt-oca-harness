# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest is a valid v1.0 of exactly ``sizeof(manifest_t)``; it boots.

The shipped primary is asserted, not mutated, and the ROM must not fetch an extension.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR
# Match the read start, not its span: the flash model records one byte past each read.
_EXTRA_ADDR = mm.PRIMARY_MANIFEST_OFFSET + mm.MANIFEST_SIZE


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test(
    sep_rom_ot_secure_boot_test
):
    """v1.0 with manifest_length 1184 is accepted, and the primary boots."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + (
        "LC=PROD",
        "MANIFEST_HASH_OK",
        "PLD_HASH_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # A bare "MANIFEST_ERR=" forbids every structural and cryptographic verdict.
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "CRYPTO_FAIL=",
        "MANIFEST_HASH_MISMATCH",
        "RSA_VERIFY_FAIL",
        "PLD_HASH_MISMATCH",
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

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced, or the accepted slot would not be graded on a completed "
            f"crypto chain"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        fd.assert_clean_key_fuses(image)
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
        # sep_manifest_mutate refuses no-op writes, so the shipped values are asserted.
        # The manifest bounds mirror a ROM #define by hand; check they still agree.
        fd.assert_rom_manifest_bounds()
        major, minor = mm.manifest_version(buf, "primary")
        length = mm.manifest_length(buf, "primary")
        assert major == mm.MANIFEST_MAJOR_VERSION, (
            f"primary manifest_version_major is {major}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}: the slot under test is supposed to be "
            f"the ACCEPTED one and would be refused as BAD_VERSION"
        )
        assert minor == 0, (
            f"primary manifest_version_minor is {minor}, expected 0: this testcase "
            f"is the minor-0 arm, and a non-zero minor would send the length down "
            f"the range rule instead of the exact-match one"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected exactly "
            f"{mm.MANIFEST_SIZE} (sizeof(manifest_t)): the minor-0 arm demands "
            f"equality, so any other value would be refused as BAD_LENGTH"
        )
        assert (
            bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), "primary manifest_identifier is not OCAC"
        pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary declares %d.%d with "
            "manifest_length %d == sizeof(manifest_t) -- the minor-0 arm's "
            "satisfied case. It passes payload_hash, every TOC image digest, "
            "manifest_hash over the signed region and RSA verification against the dev0 "
            "modulus, and the modulus it carries hashes to the ROM's compiled-in "
            "slot-0 digest",
            major,
            minor,
            length,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, 0, mm.MANIFEST_SIZE),
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

        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            _EXTRA_ADDR,
            f"manifest_length is exactly sizeof(manifest_t) ({mm.MANIFEST_SIZE}), so "
            f"load_manifest_extra() returns without reading and a fetch beginning "
            f"there would mean the ROM did not act on the declared length",
        )

        rds = ev.reads(flash.get_transactions())
        b_hit = ev.covering_read(rds, mm.BACKUP_MANIFEST_OFFSET)
        assert b_hit is None, (
            f"read[{b_hit[0] if b_hit else '?'}] covered the backup manifest "
            f"address 0x{mm.BACKUP_MANIFEST_OFFSET:x}: the ROM fell over to the "
            f"backup, so the primary was not accepted. Transactions: "
            f"{ev.summarize(flash.get_transactions(), self._image_len)}"
        )
        self.logger.info(
            "CHK-LENGTH-RULE: primary@%d declared v%d.0 with manifest_length %d, was "
            "accepted with the only MANIFEST_HASH_OK@%d and booted; no read began at "
            "0x%06x and none covered the backup slot, so the minor-0 exact-match arm "
            "was satisfied and no failover occurred",
            i_psrc,
            mm.MANIFEST_MAJOR_VERSION,
            mm.MANIFEST_SIZE,
            i_hash,
            _EXTRA_ADDR,
        )
