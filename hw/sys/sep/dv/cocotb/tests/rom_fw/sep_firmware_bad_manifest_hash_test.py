# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest's stored hash disagrees with its signed region; the backup boots.

Only the stored ``manifest_hash`` (outside the signed region) is changed, so it is the sole defect.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
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

_MANIFEST_ERR_HASH_MISMATCH = mm.boot_err("OCA_FAIL_MANIFEST_HASH")


@pyuvm.test()
class sep_firmware_bad_manifest_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's manifest_hash does not match its signed region -> the backup boots."""

    # The manifest-hash check is silent; its error line is the defect marker.
    primary_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_HASH_MISMATCH:08x}"
    primary_expected_error = _MANIFEST_ERR_HASH_MISMATCH
    primary_expected_rsa_starts = 0
    # Refused after the full body is read and before key authorization.
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ("PUBK_SEL=",)
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_hash(buf, "primary")
        computed = mm.signed_region_hash(buf, "primary")
        assert before == computed, (
            f"primary manifest_hash {before.hex()} already disagrees with "
            f"the signed-region hash {computed.hex()}: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        mm.corrupt_manifest_hash(buf, "primary")
        after = mm.manifest_hash(buf, "primary")
        assert after != before, "the manifest_hash write did not land"
        assert mm.signed_region_hash(buf, "primary") == computed, (
            "the signed-region digest changed, so the mutation reached inside the signed "
            "region: the rejection would no longer be attributable to the stored "
            "hash alone"
        )
        self.logger.info(
            "CHK-STIMULUS-HASH: primary manifest_hash %s -> %s while sha256(signed region) "
            "stays %s, so the stored copy is the only defect",
            before.hex(),
            after.hex(),
            computed.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
