# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload_offset lies inside its own manifest body; the backup boots.

payload_offset lies outside the signed region, so the manifest stage passes and
``oca_locate_payload()`` refuses the slot with ``OCA_FAIL_PAYLOAD_LOCATION`` before the fetch.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_OVERLAP = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_TOKEN = "PAYLOAD_LOC_FAIL"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)
# Offsets stay 8-byte aligned and non-zero so the location check is the only rule broken.
_OFFSET_STEP = 8
_OFFSET_MIN = _OFFSET_STEP


@pyuvm.test()
class sep_firmware_payload_overlaps_manifest_test(sep_primary_fail_backup_boot_base):
    """Primary payload_offset inside the manifest body -> refused -> backup boots."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = ERR_PAYLOAD_OVERLAP
    primary_defect_marker = _TOKEN
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = ("FLASH_READ_OOB", "PAYLOAD_TOO_LARGE", "DECRYPT_OK")
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this row is the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about"
            )
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        m_len = mm.manifest_length(buf, "primary")
        seed = self.random_seed()
        offset = SepSeededRng(seed).choice(range(_OFFSET_MIN, m_len, _OFFSET_STEP))
        self._overlap_src = mm.slot_base("primary") + offset
        was = pm.set_overlapping_payload_offset(buf, "primary", offset)
        self._offset = offset
        self._served = offset.to_bytes(8, "little")
        stored = bytes(
            buf[
                mm.slot_base("primary") + pm.OFF_BOOT_PAYLOAD_OFFSET : mm.slot_base("primary")
                + pm.OFF_BOOT_PAYLOAD_OFFSET
                + 8
            ]
        )
        assert stored == self._served, (
            f"primary OCA payload_offset reads {stored.hex()} after the "
            f"write, expected {self._served.hex()}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-OVERLAP: seed %d drew payload_offset %d -> %d, "
            "which is inside the %d-byte manifest body and 8-byte aligned, so "
            "oca_locate_payload must refuse it as %s. The field lies outside the "
            "signed region and the payload material is not moved, because the "
            "refusal precedes the fetch. The device must serve %s at flash 0x%06x",
            seed,
            was,
            offset,
            m_len,
            _TOKEN,
            stored.hex(),
            mm.slot_base("primary") + pm.OFF_BOOT_PAYLOAD_OFFSET,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._overlap_src,
            f"the primary declared payload_offset {self._offset}, inside its own "
            f"manifest body, so oca_locate_payload must refuse the slot before the "
            f"payload fetch is ever issued",
        )

        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_BOOT_PAYLOAD_OFFSET,
            self._served,
            "primary OCA payload_offset",
        )
