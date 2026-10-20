# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary payload starts four bytes off an 8-byte boundary; the backup boots.

The payload bytes and every authenticated field remain valid. Only the unsigned
``payload_offset`` and physical placement change, so the ROM must reject the
misaligned source with ``OCA_FAIL_PAYLOAD_LOCATION`` before reading it.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_ERR_PAYLOAD_LOCATION = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_LOCATION_FAIL = "PAYLOAD_LOC_FAIL"
_MISALIGNMENT = 4

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)


@pyuvm.test()
class sep_firmware_primary_payload_offset_misaligned_test(sep_primary_fail_backup_boot_base):
    """A valid primary payload at address 4 modulo 8 is refused before its fetch."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = _ERR_PAYLOAD_LOCATION
    primary_defect_marker = _LOCATION_FAIL
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = ("FLASH_READ_OOB", "PAYLOAD_TOO_LARGE", "DECRYPT_OK", "PAYLOAD_OK")
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert not pm.is_encrypted(buf, "primary"), (
            f"primary payload carries encrypted_payload = 1; this test requires the "
            f"cleartext image ({self.flash_image}) so moving the stored bytes preserves "
            f"the authenticated payload exactly"
        )
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        assert pm.OFF_PAYLOAD_OFFSET >= mm.SIGNED_REGION_END, (
            "payload_offset is signed; changing it would invalidate the signature"
        )
        base = mm.slot_base("primary")
        old_src = pm.payload_base(buf, "primary")
        span = pm.manifest_payload_length(buf, "primary")
        old_offset = old_src - base
        new_offset = old_offset + _MISALIGNMENT
        self._payload_src = base + new_offset
        assert old_src % 8 == 0 and self._payload_src % 8 == _MISALIGNMENT, (
            f"payload move 0x{old_src:x} -> 0x{self._payload_src:x} does not create "
            f"the intended 4-modulo-8 source"
        )
        assert self._payload_src + span <= mm.slot_base("backup"), (
            f"moved primary payload ends at 0x{self._payload_src + span:x}, outside "
            "the primary slot"
        )

        payload = bytes(buf[old_src : old_src + span])
        buf[self._payload_src : self._payload_src + span] = payload
        buf[old_src : old_src + _MISALIGNMENT] = bytes(_MISALIGNMENT)
        field = base + pm.OFF_PAYLOAD_OFFSET
        self._served = struct.pack("<q", new_offset)
        buf[field : field + len(self._served)] = self._served

        assert bytes(buf[self._payload_src : self._payload_src + span]) == payload, (
            "moving the payload changed its bytes"
        )
        assert pm.payload_base(buf, "primary") == self._payload_src
        assert mm.manifest_hash(buf, "primary") == mm.signed_region_hash(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        mm.verify_public_key(buf, "primary")
        pm.verify_sealed(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-ALIGN: primary payload_offset 0x%x -> 0x%x in "
            "the unsigned tail; copied the unchanged %d-byte sealed payload from "
            "0x%06x to 0x%06x (%d modulo 8)",
            old_offset,
            new_offset,
            span,
            old_src,
            self._payload_src,
            self._payload_src % 8,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._payload_src,
            "the resolved primary payload source is not 8-byte aligned",
        )
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_PAYLOAD_OFFSET,
            self._served,
            "primary OCA payload_offset",
        )
