# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest naming an unassigned public-key source (PyUVM).

The backup's ``public_key_sel.selection`` is 3, an encoding that names no key source.
This ROM reports it as ``BAD_KEY_SEL``; it has no ``INVALID_KEY_INDEX`` status.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BAD_SELECTION = 3
_BAD_PUBK_SEL_VALUE = (_BAD_SELECTION & 0x7) << 4


@pyuvm.test()
class sep_firmware_backup_invalid_public_key_selection_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup names key source 3 -> terminal."""

    backup_defect_marker = "BAD_KEY_SEL"
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # The selection must be rejected before any key is loaded or verified.
    extra_forbidden = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK",
                       "BAD_KEY_IDX", "FUSE_KEY_EMPTY")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=_BAD_SELECTION, index=0)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _BAD_PUBK_SEL_VALUE, (
            f"public_key_sel encoded as 0x{got:04x}, expected "
            f"0x{_BAD_PUBK_SEL_VALUE:04x}"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-PUBKSEL: backup public_key_sel=0x%04x "
            "(selection=%d, unassigned), TBS re-hashed", got, _BAD_SELECTION,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection and would terminate the run first"
        )
        assert image.field_int("CHIPLET_PUBK_REVOKE") == 0, (
            "CHIPLET_PUBK_REVOKE must be 0; revocation is keyed off the selected "
            "index and would produce a different verdict"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        marker = f"PUBK_SEL=0x{_BAD_PUBK_SEL_VALUE:08x}"
        assert any(marker in line for line in console), (
            f"ROM never printed {marker}: the BAD_KEY_SEL verdict cannot be "
            f"attributed to the selection this test planted. Console: {console}"
        )
        self.logger.info("CHK-PUBKSEL-ECHO: ROM read %s", marker)
