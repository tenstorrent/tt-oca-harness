# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A cleartext image's TOC digest is zeroed; the primary's payload hash fails and the backup boots.

Nothing is re-sealed, so ``manifest_hash`` and the signature still verify; the library
refuses the payload with ``OCA_FAIL_PAYLOAD_HASH``, which prints no marker of its own.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_HASH_MISMATCH = mm.boot_err("OCA_FAIL_PAYLOAD_HASH")

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)
_ENTRY_INDEX = 0
_ZERO_DIGEST = b"\x00" * 32


@pyuvm.test()
class sep_firmware_cleartext_image_corrupt_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's cleartext image digest is zeroed -> payload hash fails -> backup boots."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = ERR_PAYLOAD_HASH_MISMATCH
    primary_defect_marker = f"MANIFEST_ERR=0x{ERR_PAYLOAD_HASH_MISMATCH:08x}"
    # The payload hash is checked after the signature, so the primary's signature verifies.
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    # Payload-stage arms with their own marker that precede the hash comparison.
    primary_absent = ("PAYLOAD_LOC_FAIL", "PAYLOAD_TOO_LARGE", "FLASH_READ_OOB", "DECRYPT_OK")
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this row is the "
                f"CLEARTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about. For an encrypted payload "
                f"payload_hashed_length spans the whole ciphertext rather than the "
                f"TOC region, so the geometry this row depends on would differ"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        entries = pm.toc_entries(buf, "primary")
        assert len(entries) == 1, (
            f"primary TOC declares {len(entries)} images; this row plants the digest "
            f"of the single shipped image, and entry {_ENTRY_INDEX} is only the whole "
            f"list when the payload carries one"
        )
        hashed = pm.payload_hashed_length(buf, "primary")
        field = pm.toc_entry_at(_ENTRY_INDEX) + pm.E_HASH
        assert field + 32 <= hashed, (
            f"payload_hashed_length is {hashed}, which does not reach entry "
            f"{_ENTRY_INDEX}'s digest at {field}..{field + 32}: payload_hash would "
            f"not cover the edit and verify_payload_hash would ACCEPT the slot"
        )
        # No re-seal, or the ROM refuses the slot on the entry digest or hash chain instead.
        self._served = pm.corrupt_toc_entry_hash(
            buf, "primary", _ENTRY_INDEX, value=_ZERO_DIGEST, reseal=False
        )
        assert self._served == _ZERO_DIGEST, (
            f"the stored digest is {self._served.hex()} but a cleartext payload "
            f"stores what was written; the mutation reached the wrong bytes"
        )
        mm.verify_layout(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        try:
            pm.verify_sealed(buf, "primary", check_toc=False)
        except AssertionError as e:
            assert "payload_hash does not cover" in str(e), f"unexpected seal failure: {e}"
        else:
            raise AssertionError("primary payload_hash still covers the edited payload")
        self.logger.info(
            "CHK-STIMULUS-IMAGE-HASH: primary TOC entry %d digest -> %s, with the "
            "image BODY left exactly as shipped and NOTHING re-sealed. "
            "payload_hashed_length is %d, so payload_hash covers the field at "
            "payload offset %d, and the mutator proved offline that the ROM's own "
            "sha256(payload[:%d]) no longer matches the stored payload_hash while "
            "manifest_hash and the RSA signature still verify. The field sits at "
            "flash 0x%06x and the device must serve %s there",
            _ENTRY_INDEX,
            self._served.hex(),
            hashed,
            field,
            hashed,
            mm.slot_base("primary") + self._payload_offset + field,
            self._served.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            self._payload_offset + pm.toc_entry_at(_ENTRY_INDEX) + pm.E_HASH,
            self._served,
            f"primary TOC entry {_ENTRY_INDEX} image digest",
        )
