# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload_offset lies inside its own manifest header; the backup boots.

The ROM must refuse it in ``validate_manifest_header``, before the integrity check,
staging and fetch. Needs ``+sep_crypto_edn_force``: the backup runs RSA-3072 on OTBN.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_no_payload_images_base as npi
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

ERR_PAYLOAD_OVERLAP = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_TOKEN = "PAYLOAD_LOC_FAIL"

# Zero and unaligned offsets fail earlier with MANIFEST_ERR_BAD_LENGTH.
_OFFSET_STEP = 8
_OFFSET_MIN = _OFFSET_STEP

_OTHER_TOKENS = td.OTHER_PAYLOAD_TOKENS


@pyuvm.test()
class sep_firmware_payload_overlaps_manifest_test(sep_primary_fail_backup_boot_base):
    """Primary payload_offset inside the manifest header -> refused -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_OVERLAP
    primary_defect_marker = ""
    # OCA authenticates the body before it interprets the unsigned payload location.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    extra_required = (_TOKEN, "MANIFEST_HASH_OK", "PAYLOAD_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + [td.DECRYPT_START, "CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        + list(_OTHER_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

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
            "oca_locate_payload must refuse it as %s. The payload location is in "
            "the OCA unsigned tail, while the authenticated body remains valid, "
            "and the payload material is not moved, because the refusal precedes "
            "the fetch. The device must serve %s at flash 0x%06x",
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

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_OVERLAP:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_token = fd.assert_slot_attributed(console, _TOKEN, after=i_psrc, before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_token, before=i_bsrc)

        n_hash = fd.count(console, "MANIFEST_HASH_OK")
        assert n_hash == 2, (
            f"MANIFEST_HASH_OK appeared {n_hash} times, expected once per slot: "
            f"OCA authenticates each body before locating its payload. Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK", after=i_psrc)
        assert i_hash < i_token, (
            f"primary MANIFEST_HASH_OK@{i_hash} does not precede {_TOKEN}@{i_token}; "
            f"the OCA body was not authenticated before its unsigned location was used"
        )

        i_payload_ok = fd.first_index(console, "PAYLOAD_OK")
        assert i_bsrc < i_payload_ok, (
            f"PAYLOAD_OK@{i_payload_ok} precedes backup read@{i_bsrc}: the invalid "
            f"primary location reached payload validation"
        )
        self.logger.info(
            "CHK-PAYLOAD-LOCATION: primary@%d -> MANIFEST_HASH_OK@%d -> %s@%d "
            "-> %s@%d -> backup@%d -> PAYLOAD_OK@%d",
            i_psrc,
            i_hash,
            _TOKEN,
            i_token,
            slot_err,
            i_err,
            i_bsrc,
            i_payload_ok,
        )

        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._overlap_src,
            f"the primary declared payload_offset {self._offset}, inside its own "
            f"manifest header, so validate_manifest_header must refuse the slot "
            f"before the payload fetch is ever issued",
        )

        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            pm.OFF_BOOT_PAYLOAD_OFFSET,
            self._served,
            "primary OCA payload_offset",
        )
