# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest selecting a ROM key slot that has no compiled-in digest.

An empty slot must fail before ``RSA_VERIFY_START``, or the manifest's own modulus is trusted.
Needs a ``TEST_BUILD=0`` ROM: the default build compiles test digests into slots 1-5.
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

_EMPTY_SLOT = 1
# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0.
_PUBK_SEL_VALUE = _EMPTY_SLOT & 0xF


@pyuvm.test()
class sep_firmware_backup_unpopulated_rom_key_slot_test(sep_backup_manifest_fail_base):
    """Primary fails over -> backup selects empty ROM key slot 1 -> terminal."""

    backup_defect_marker = "ROM_KEY_EMPTY"
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK",
                       "BAD_KEY_IDX", "BAD_KEY_SEL", "FUSE_KEY_EMPTY")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=0, index=_EMPTY_SLOT)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"public_key_sel encoded as 0x{got:04x}, expected 0x{_PUBK_SEL_VALUE:04x} "
            f"(selection=ROM_KEY, index={_EMPTY_SLOT})"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-EMPTY-SLOT: backup public_key_sel=0x%04x "
            "(ROM key slot %d, no compiled-in digest), TBS re-hashed",
            got, _EMPTY_SLOT,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection and would terminate the run first"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: slot "
            f"{_EMPTY_SLOT} must not be revoked, or the rejection would be "
            f"attributable to revocation rather than to the empty digest"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        marker = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"
        assert any(marker in line for line in console), (
            f"ROM never printed {marker}: the ROM_KEY_EMPTY verdict cannot be "
            f"attributed to the slot this test selected. Console: {console}"
        )
        self.logger.info("CHK-EMPTY-SLOT-ECHO: ROM read %s", marker)
