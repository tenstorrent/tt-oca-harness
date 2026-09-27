# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary payload declares no SEP_BL1 image; the backup boots.

The primary's BL1 entry is relabelled SEPBL2 and the slot re-sealed, so the primary
passes its crypto chain and is refused only at the BL1-presence check (NO_BL1_IMAGE).
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
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

_MANIFEST_ERR_NO_BL1_IMAGE = pm.MANIFEST_ERR_NO_BL1

_NO_BL1 = "NO_BL1_IMAGE"
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"

_RELABEL_TYPE = pm.IMAGE_TYPE_SEP_BL2


@pyuvm.test()
class sep_firmware_manifest_primary_missing_sepbl1_test(sep_primary_fail_backup_boot_base):
    """Primary TOC declares SEPBL2 where BL1 was -> failover -> the backup boots."""

    # Empty: the base's defect-marker path would also require CRYPTO_FAIL=.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_NO_BL1_IMAGE
    # The BL1 check runs after crypto validation, so the primary verifies once too.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = (
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "PLD_HASH_MISMATCH",
        "MANIFEST_HASH_MISMATCH",
        "MANIFEST_ALL_FAILED",
        "IMAGE_HASH_MISMATCH",
        "IMAGE_ORDER_BAD",
        "IMAGE_LEN_ZERO",
        "IMAGE_LEN_ALIGN",
        "TOC_REGION_OOB=",
        "TOC_PLEN_MISMATCH=",
        "BL1_ADDR_RANGE",
        "BL1_ENTRY_RANGE",
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        entry = pm.find_image(buf, "primary")
        before = pm.entry_type(buf, entry)
        assert before == pm.IMAGE_TYPE_SEP_BL1, (
            f"primary TOC BL1 entry type is {before!r}, expected "
            f"{pm.IMAGE_TYPE_SEP_BL1!r}: the shipped image is not the valid "
            f"baseline this testcase relabels away from"
        )
        self.logger.info("CHK-STIMULUS-BL1-BEFORE: %s", pm.describe_bl1(buf, "primary"))
        changed = pm.retype_bl1_image(buf, "primary", _RELABEL_TYPE)
        assert changed == before
        types = [pm.entry_type(buf, e) for e in pm.toc_entries(buf, "primary")]
        assert pm.IMAGE_TYPE_SEP_BL1 not in types, (
            f"primary TOC still declares a SEP_BL1 image: {types}"
        )
        self.logger.info(
            "CHK-STIMULUS-MISSING-BL1: primary TOC entry @0x%x relabelled "
            "%r -> %r, leaving types %s and no SEP_BL1; the image BODY is "
            "untouched so its digest still verifies, and the slot is re-sealed so "
            "the TOC change does not surface as PLD_HASH_MISMATCH",
            entry,
            before,
            _RELABEL_TYPE,
            types,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_defect = fd.assert_slot_attributed(console, _NO_BL1, after=i_psrc, before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_defect, before=i_bsrc)

        i_pcrypto = fd.first_index(console, _CRYPTO_OK)
        assert i_psrc < i_pcrypto < i_defect, (
            f"{_CRYPTO_OK}@{i_pcrypto} does not sit between the primary read"
            f"@{i_psrc} and {_NO_BL1}@{i_defect}: the primary was refused before "
            f"its crypto chain finished, so the verdict is not the BL1-presence "
            f"branch's. Console: {console}"
        )
        self.logger.info(
            "CHK-MISSING-BL1: primary read@%d -> %s@%d -> %s@%d -> %s@%d -> backup "
            "read@%d; the primary passed the whole crypto chain and was refused "
            "only for having no SEP_BL1 image",
            i_psrc,
            _CRYPTO_OK,
            i_pcrypto,
            _NO_BL1,
            i_defect,
            slot_err,
            i_err,
            i_bsrc,
        )
