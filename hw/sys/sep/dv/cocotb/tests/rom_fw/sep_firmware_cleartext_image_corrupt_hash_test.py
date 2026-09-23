# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A cleartext image's TOC digest is zeroed; the primary's payload hash fails and the backup boots.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_no_payload_images_base as npi
from rom_fw import sep_toc_defect as td
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_HASH_MISMATCH = 0x0003_0017
ERR_HASH_MISMATCH = 0x0003_000B
ERR_IMAGE_HASH_MISMATCH = ted.ERR_IMAGE_HASH_MISMATCH
ERR_IMAGE_ALIGN = 0x0003_001B

_ENTRY_INDEX = 0
_ZERO_DIGEST = b"\x00" * 32
_TOKEN = "PLD_HASH_MISMATCH"
_HASH_OK = "PLD_HASH_OK"

_OTHER_TOKENS = tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != _TOKEN)
assert len(_OTHER_TOKENS) == len(td.OTHER_PAYLOAD_TOKENS) - 1, (
    f"{_TOKEN!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this arm's "
    f"token would be neither required by this row nor forbidden by its neighbours; "
    f"the swap-test defence has silently lapsed"
)
for _must_stay in ("PLD_HASH_FAIL=", "IMAGE_HASH_MISMATCH", "IMAGE_HASH_TIMEOUT"):
    assert _must_stay in _OTHER_TOKENS, (
        f"{_must_stay!r} must stay forbidden: it is either the same failure reported "
        f"through the secure-boot-off branch, or the per-entry arm a re-sealed "
        f"variant of this mutation would land on"
    )
_TIMEOUT_TOKEN = "PLD_HASH_TIMEOUT"

_NEIGHBOUR_ERRORS = [
    f"MANIFEST_ERR=0x{c:08x}" for c in (
        ERR_HASH_MISMATCH, ERR_IMAGE_HASH_MISMATCH, ted.ERR_BAD_IMAGE_TYPE,
        ted.ERR_IMAGE_OOB, ted.ERR_IMAGE_OVERLAP, ERR_IMAGE_ALIGN,
    )
]


@pyuvm.test()
class sep_firmware_cleartext_image_corrupt_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's cleartext image digest is zeroed -> payload hash fails -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_HASH_MISMATCH
    primary_defect_marker = _TOKEN
    # The payload hash is checked after the signature, so the primary's signature verifies.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    extra_required = ("MANIFEST_HASH_OK", _HASH_OK, "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + _NEIGHBOUR_ERRORS
        + [td.DECRYPT_START, _TIMEOUT_TOKEN, "MANIFEST_ALL_FAILED"]
        + list(_OTHER_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

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
        # No re-seal, or the ROM rejects the slot at IMAGE_HASH_MISMATCH instead.
        self._served = pm.corrupt_toc_entry_hash(
            buf, "primary", _ENTRY_INDEX, value=_ZERO_DIGEST, reseal=False)
        assert self._served == _ZERO_DIGEST, (
            f"the stored digest is {self._served.hex()} but a cleartext payload "
            f"stores what was written; the mutation reached the wrong bytes"
        )
        self.logger.info(
            "CHK-STIMULUS-IMAGE-HASH: primary TOC entry %d digest -> %s, with the "
            "image BODY left exactly as shipped and NOTHING re-sealed. "
            "payload_hashed_length is %d, so payload_hash covers the field at "
            "payload offset %d, and the mutator proved offline that the ROM's own "
            "sha256(payload[:%d]) no longer matches the stored payload_hash while "
            "manifest_hash and the RSA signature still verify. The field sits at "
            "flash 0x%06x and the device must serve %s there",
            _ENTRY_INDEX, self._served.hex(), hashed, field, hashed,
            mm.slot_base("primary") + self._payload_offset + field,
            self._served.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_HASH_MISMATCH:08x}"
        crypto_fail = f"CRYPTO_FAIL=0x{ERR_PAYLOAD_HASH_MISMATCH:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_token = fd.assert_slot_attributed(console, _TOKEN, after=i_psrc,
                                            before=i_bsrc)
        i_cf = fd.assert_slot_attributed(console, crypto_fail, after=i_token,
                                         before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_cf,
                                          before=i_bsrc)

        n_ok = fd.count(console, _HASH_OK)
        assert n_ok == 1, (
            f"{_HASH_OK} appeared {n_ok} times, expected exactly 1 (the backup's): "
            f"the primary's payload hash must FAIL, and only the backup's may pass. "
            f"Console: {console}"
        )
        i_ok = fd.first_index(console, _HASH_OK)
        assert i_bsrc < i_ok, (
            f"{_HASH_OK}@{i_ok} precedes the backup read@{i_bsrc}, so it is the "
            f"primary's: its payload hash passed and this row proves nothing. "
            f"Console: {console}"
        )

        n_hash = fd.count(console, "MANIFEST_HASH_OK")
        assert n_hash == 2, (
            f"MANIFEST_HASH_OK appeared {n_hash} times, expected exactly 2 (one per "
            f"slot): payload_hash sits inside the TBS and was left untouched, so the "
            f"primary's manifest hash must still verify. Console: {console}"
        )
        i_mh = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_psrc < i_mh < i_token, (
            f"the primary's MANIFEST_HASH_OK@{i_mh} does not sit between its "
            f"read@{i_psrc} and {_TOKEN}@{i_token}. Console: {console}"
        )
        self.logger.info(
            "CHK-PAYLOAD-HASH-RULE: primary@%d -> MANIFEST_HASH_OK@%d -> %s@%d -> "
            "%s@%d -> %s@%d, inside its own attempt and after its signature "
            "verified; %s appeared once and only after the backup read@%d, so the "
            "primary's comparison reached a verdict of mismatch and the untouched "
            "backup booted",
            i_psrc, i_mh, _TOKEN, i_token, crypto_fail, i_cf, slot_err, i_err,
            _HASH_OK, i_bsrc,
        )

        fd.assert_served_field(
            self.logger, flash, "primary",
            self._payload_offset + pm.toc_entry_at(_ENTRY_INDEX) + pm.E_HASH,
            self._served, f"primary TOC entry {_ENTRY_INDEX} image digest",
        )
