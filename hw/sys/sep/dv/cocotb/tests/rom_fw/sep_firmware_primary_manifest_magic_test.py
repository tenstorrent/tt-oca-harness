# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest magic is not OCAC; the backup boots.

``oca_peek_manifest()`` refuses the primary with ``OCA_FAIL_MAGIC`` before the body
is read, so the attempt never prints ``OCA_BODY=``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_BAD_MAGIC,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_BAD_MAGIC = b"\x99\x99\x99\x99"


@pyuvm.test()
class sep_firmware_primary_manifest_magic_test(sep_primary_fail_backup_boot_base):
    """Primary magic is not OCAC -> BAD_MAGIC -> the backup boots."""

    primary_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}"
    primary_expected_error = MANIFEST_ERR_BAD_MAGIC
    primary_expected_rsa_starts = 0
    primary_absent = ("OCA_BODY=", "MFST_VER=")
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        before = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert before == mm.MANIFEST_MAGIC, (
            f"primary magic is already {before!r}, expected "
            f"{mm.MANIFEST_MAGIC!r}: the shipped image is not the valid baseline "
            f"this testcase mutates away from"
        )
        mm.break_magic(buf, "primary", _BAD_MAGIC)
        after = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert after == _BAD_MAGIC, (
            f"primary magic is {after!r} after the write, expected {_BAD_MAGIC!r}"
        )
        self.logger.info(
            "CHK-STIMULUS-MAGIC: primary magic %r -> %r; the magic is the slot's only defect",
            before,
            after,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
