# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup payload declares no SEP_BL1 image; with both slots refused the ROM halts.

A package_id mismatch refuses the primary; the backup passes the crypto chain and
is then refused because its TOC has no SEP_BL1 entry.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_payload_fail_base import sep_backup_payload_fail_base
from rom_fw.sep_usage_constraint_base import (
    EFUSE_PRELOAD,
    MANIFEST_ERR_LC_USAGE_CONSTRAINT,
)

_MANIFEST_ERR_NO_BL1_IMAGE = 0x0003_0008

_NO_BL1 = "NO_BL1_IMAGE"

_SELECTOR_MASK = 0x42
_REJECT_INDEX = 1

_RELABEL_TYPE = pm.IMAGE_TYPE_SEP_BL2


@pyuvm.test()
class sep_firmware_manifest_backup_missing_sepbl1_test(
        sep_backup_payload_fail_base):
    """Backup TOC declares SEPBL2 where BL1 was -> both slots refused -> halt."""

    backup_defect_marker = _NO_BL1
    expected_error = _MANIFEST_ERR_NO_BL1_IMAGE
    primary_expected_error = MANIFEST_ERR_LC_USAGE_CONSTRAINT
    efuse_preload = EFUSE_PRELOAD
    # Only the package_id arm may refuse the primary, and only the BL1 check the backup.
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER,
                       "MANIFEST_HASH_MISMATCH", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "IMAGE_HASH_MISMATCH",
                       "IMAGE_ORDER_BAD", "IMAGE_LEN_ZERO", "IMAGE_LEN_ALIGN",
                       "TOC_REGION_OOB=", "TOC_PLEN_MISMATCH=",
                       "BL1_ADDR_RANGE", "BL1_ENTRY_RANGE")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
        lc = image.lc_raw()
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}: the backup must reach the crypto chain, "
            f"which is enforced by lifecycle in PROD"
        )

    def corrupt_primary(self, buf: bytearray) -> None:
        index = fd.plant_device_id_defect(buf, "primary", "package_id",
                                          _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-TRIGGER: primary selector_bits[8..15] = 0x%02x, so the "
            "ROM must read package_id words %s and refuse on word %d with "
            "MANIFEST_ERR=0x%08x -- a different code from the backup's 0x%08x",
            _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
            MANIFEST_ERR_LC_USAGE_CONSTRAINT, _MANIFEST_ERR_NO_BL1_IMAGE,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        before = pm.bl1_field(buf, "backup", pm.E_TYPE)
        assert before == pm.IMAGE_TYPE_SEP_BL1, (
            f"backup TOC BL1 entry type is 0x{before:x}, expected "
            f"0x{pm.IMAGE_TYPE_SEP_BL1:x}: the shipped image is not the valid "
            f"baseline this testcase relabels away from"
        )
        self.logger.info("CHK-STIMULUS-BL1-BEFORE: %s", pm.describe_bl1(buf, "backup"))
        entry = pm.retype_bl1_image(buf, "backup", _RELABEL_TYPE)
        types = [pm._u64(buf, e + pm.E_TYPE) for e in pm.toc_entries(buf, "backup")]
        assert pm.IMAGE_TYPE_SEP_BL1 not in types, (
            f"backup TOC still declares a SEP_BL1 image: {[hex(t) for t in types]}"
        )
        # The backup must pass the crypto chain so that only the BL1 check refuses it.
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-MISSING-BL1: backup TOC entry @0x%x relabelled "
            "0x%x -> 0x%x, leaving types %s and no SEP_BL1; the slot is re-sealed "
            "and its modulus still hashes to the ROM's slot-0 digest, so it will "
            "pass the whole crypto chain and be refused only by the BL1 check",
            entry, before, _RELABEL_TYPE, [hex(t) for t in types],
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # Three constraint arms share this error code; confirm the package_id arm fired.
        fd.assert_device_id_mismatch(self.logger, console, "package_id",
                                     _REJECT_INDEX)
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        fd.assert_slot_attributed(console, fd.PACKAGE_MARKER, after=i_psrc,
                                  before=i_bsrc)
        self.logger.info(
            "CHK-TRIGGER: %s inside the primary attempt (read@%d, backup read@%d)",
            fd.PACKAGE_MARKER, i_psrc, i_bsrc,
        )
