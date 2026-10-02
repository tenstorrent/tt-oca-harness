# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest declares an unsupported major version; the backup boots.

Only the primary's major version is wrong (2), so the library refuses it with
``OCA_FAIL_FORMAT_VERSION_MISMATCH`` after the body is read and before key authorization.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
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

_MANIFEST_ERR_BAD_VERSION = mm.boot_err("OCA_FAIL_FORMAT_VERSION_MISMATCH")

_BAD_MAJOR_VERSION = 2

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_invalid_test(sep_primary_fail_backup_boot_base):
    """Primary major version is not 1 -> refused -> the backup boots."""

    primary_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}"
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ("PUBK_SEL=",)
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "primary")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert (
            bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), (
            "primary magic is not OCAC, so OCA_FAIL_MAGIC would preempt "
            "the version check and the asserted code would be wrong"
        )
        mm.set_manifest_version(buf, "primary", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "primary")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"primary manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        length = mm.manifest_length(buf, "primary")
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused on its length instead of its version"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d, with "
            "minor 0, length %d (the body size) and magic OCAC all left VALID, so "
            "the major version is the only field the library can refuse this slot on",
            before[0],
            after[0],
            length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            _VERSION_LENGTH_OFF,
            struct.pack("<HHI", _BAD_MAJOR_VERSION, 0, mm.MANIFEST_SIZE),
            "primary manifest_version_major/minor + manifest_length",
        )
