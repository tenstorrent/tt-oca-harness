# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary payload declares no SEP_BL1 image; the backup boots.

The BL1 entry is relabelled SEPBL2 and the slot re-sealed, so only the BL1-presence
check refuses the primary, with ``NO_BL1_IMAGE`` and ``OCA_BOOT_ERR_NO_BL1``.
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

_RELABEL_TYPE = pm.IMAGE_TYPE_SEP_BL2


@pyuvm.test()
class sep_firmware_manifest_primary_missing_sepbl1_test(sep_primary_fail_backup_boot_base):
    """Primary TOC declares SEPBL2 where BL1 was -> failover -> the backup boots."""

    primary_defect_marker = _NO_BL1
    primary_expected_error = _MANIFEST_ERR_NO_BL1_IMAGE
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "placement"
    primary_ordered = ("PAYLOAD_OK",)
    primary_absent = ("BL1_ADDR_RANGE", "BL1_SRAM_EXEC_DISABLED", "BL1_SIZE", "BL1_ENTRY_RANGE")
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        golden = bytes(buf)
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
        rules = pm.spec_rule_violations(buf, "primary")
        assert rules == [], f"the relabelled primary TOC also breaks spec rules {rules}"
        type_at = entry - pm.payload_base(buf, "primary") + pm.E_TYPE
        changed = {i for r in pm.plaintext_diff(golden, bytes(buf), "primary") for i in r}
        assert changed and changed <= set(range(type_at, type_at + 16)), (
            f"the relabel changed cleartext bytes {sorted(changed)[:16]} outside the entry "
            f"type at payload offset {type_at}"
        )
        self.logger.info(
            "CHK-STIMULUS-MISSING-BL1: primary TOC entry @0x%x relabelled "
            "%r -> %r, leaving types %s and no SEP_BL1; the image BODY is "
            "untouched so its digest still verifies, and the slot is re-sealed so "
            "the TOC change does not surface as a hash failure",
            entry,
            before,
            _RELABEL_TYPE,
            types,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
