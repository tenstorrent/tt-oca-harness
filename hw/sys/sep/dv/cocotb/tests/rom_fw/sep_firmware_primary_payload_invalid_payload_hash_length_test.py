# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares ``payload_hashed_length`` = 0; the backup boots.

The slot is re-signed, so it passes the manifest stage; the ROM must refuse the zero
length with ``OCA_FAIL_PAYLOAD_TOC`` before any digest and fail over.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
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

_MANIFEST_ERR_PAYLOAD_TOC = mm.boot_err("OCA_FAIL_PAYLOAD_TOC")

_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_primary_payload_invalid_payload_hash_length_test(
    sep_primary_fail_backup_boot_base
):
    """Primary payload_hashed_length is 0 -> refused -> the backup boots."""

    primary_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_PAYLOAD_TOC:08x}"
    primary_expected_error = _MANIFEST_ERR_PAYLOAD_TOC
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = ("PAYLOAD_LOC_FAIL", "PAYLOAD_TOO_LARGE", "FLASH_READ_OOB", "DECRYPT_OK")
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "primary"), (
            "primary payload is encrypted: payload_hashed_length is then the "
            "ciphertext length and a zero value takes a different arm"
        )
        p_len = pm.manifest_payload_length(buf, "primary")
        self._bad_hashed_len = _BAD_HASHED_LEN
        self._payload_len = p_len
        was = pm.set_payload_hashed_length(buf, "primary", self._bad_hashed_len)
        now = pm.payload_hashed_length(buf, "primary")
        assert now == self._bad_hashed_len, (
            f"primary payload_hashed_length is {now} after the write, expected "
            f"{self._bad_hashed_len}; the mutation did not land"
        )
        mm.verify_layout(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: primary payload_hashed_length %d -> %d against "
            "payload_length %d, slot re-signed; the zero length is the slot's only defect",
            was,
            now,
            p_len,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_PAYLOAD_HASHED_LEN,
            struct.pack("<Q", self._bad_hashed_len),
            "primary payload_hashed_length",
        )
