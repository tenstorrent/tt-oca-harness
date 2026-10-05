# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload_offset names the backup slot's payload; the backup boots.

``payload_offset`` is outside the signed region and the backup payload equals the primary's, so
only the location bound can refuse the slot, with ``OCA_FAIL_PAYLOAD_LOCATION``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_LOCATION = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_TOKEN = "PAYLOAD_LOC_FAIL"

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)
_SLOT_STRIDE = mm.BACKUP_MANIFEST_OFFSET - mm.PRIMARY_MANIFEST_OFFSET
_WINDOW_SPAN = _SLOT_STRIDE - mm.PRIMARY_MANIFEST_OFFSET


def _window(slot: str) -> tuple[int, int]:
    base = mm.slot_base(slot)
    return base, base + _WINDOW_SPAN


@pyuvm.test()
class sep_firmware_primary_payload_offset_into_backup_test(sep_primary_fail_backup_boot_base):
    """Primary payload_offset into the backup slot -> refused -> backup boots."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = ERR_PAYLOAD_LOCATION
    primary_defect_marker = _TOKEN
    # The location is interpreted only after the body is authenticated.
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_absent = ("FLASH_READ_OOB", "PAYLOAD_TOO_LARGE", "DECRYPT_OK", "PAYLOAD_OK")
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this test is the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about"
            )
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        assert pm.OFF_PAYLOAD_OFFSET >= mm.SIGNED_REGION_END, (
            "payload_offset is inside the signed region; the primary would need re-signing"
        )
        span = pm.manifest_payload_length(buf, "primary")
        p_src = pm.payload_base(buf, "primary")
        b_src = pm.payload_base(buf, "backup")
        assert span == pm.manifest_payload_length(buf, "backup") and bytes(
            buf[p_src : p_src + span]
        ) == bytes(buf[b_src : b_src + span]), (
            "the backup payload differs from the primary's, so a redirected primary "
            "would fail its payload hash and the location bound would go untested"
        )
        p_lo, p_hi = _window("primary")
        b_lo, b_hi = _window("backup")
        assert p_hi <= b_src and b_src + span <= b_hi, (
            f"backup payload 0x{b_src:x}..0x{b_src + span:x} is not inside the backup "
            f"window 0x{b_lo:x}..0x{b_hi:x} and outside the primary window "
            f"0x{p_lo:x}..0x{p_hi:x}"
        )

        at = mm.slot_base("primary") + pm.OFF_PAYLOAD_OFFSET
        was = int.from_bytes(bytes(buf[at : at + 8]), "little", signed=True)
        offset = b_src - mm.slot_base("primary")
        self._served = offset.to_bytes(8, "little", signed=True)
        buf[at : at + 8] = self._served
        assert pm.payload_base(buf, "primary") == b_src

        assert mm.manifest_hash(buf, "primary") == mm.signed_region_hash(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        mm.verify_public_key(buf, "primary")
        pm.verify_sealed(buf, "primary")
        self._backup_src = b_src
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-INTO-BACKUP: primary payload_offset 0x%x -> 0x%x in "
            "the unsigned tail, signature unchanged; the payload resolves to flash "
            "0x%06x..0x%06x, inside the backup window 0x%x..0x%x and past the primary "
            "window 0x%x..0x%x. The bytes there equal the primary's payload, so the "
            "primary still passes payload_hash, every TOC digest and the hash chain",
            was,
            offset,
            b_src,
            b_src + span,
            b_lo,
            b_hi,
            p_lo,
            p_hi,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        hits = fd.reads_starting_at(flash, self._backup_src)
        b_idx, _ = ev.covering_read(ev.reads(flash.get_transactions()), mm.BACKUP_MANIFEST_OFFSET)
        assert len(hits) == 1 and hits[0] > b_idx, (
            f"reads starting at 0x{self._backup_src:x} are {hits}, expected exactly one "
            f"after the backup manifest read[{b_idx}]: the primary attempt fetched the "
            f"backup's payload"
        )
        self.logger.info(
            "CHK-NO-CROSS-SLOT-READ PASS: the only read at 0x%06x is read[%d], after the "
            "backup manifest read[%d]",
            self._backup_src,
            hits[0],
            b_idx,
        )

        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_PAYLOAD_OFFSET,
            self._served,
            "primary OCA payload_offset",
        )
