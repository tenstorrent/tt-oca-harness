# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest names a ROM key index outside the table -> terminal.

Index 6 == ``PUBK_SEL_NUM_ROM_KEYS`` is the smallest value the ``>=`` bound must refuse.
The bound must run before the revocation bitmap (``1u << index``) and the digest table are read.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BAD_INDEX = mm.PUBK_SEL_NUM_ROM_KEYS
# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0.
_PUBK_SEL_VALUE = _BAD_INDEX & 0xF
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_PUBK_SEL_VALUE:08x}"


@pyuvm.test()
class sep_firmware_backup_rom_key_index_invalid_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup names ROM key index 6 -> terminal."""

    backup_defect_marker = "BAD_KEY_IDX"
    expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    # PUBK_REVOKE= or ROM_KEY_EMPTY would mean the bad index reached the bitmap or digest table.
    extra_forbidden = ("PUBK_REVOKE=", "KEY_REVOKED", "ROM_KEY_EMPTY",
                       "PUBK_HASH_MISMATCH", "BAD_KEY_SEL", "FUSE_KEY_EMPTY",
                       "RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK",
                       "VERSION_ROLLBACK", "BAD_SIG_TYPE=")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "backup", selection=0, index=_BAD_INDEX)
        got = mm.get_public_key_sel(buf, "backup")
        assert got == _PUBK_SEL_VALUE, (
            f"public_key_sel encoded as 0x{got:04x}, expected "
            f"0x{_PUBK_SEL_VALUE:04x} (selection=PUBK_SEL_ROM_KEY, "
            f"index={_BAD_INDEX})"
        )
        # The index bound is reached only when selection names the ROM-key source.
        selection = (got >> 4) & 0x7
        assert selection == 0, (
            f"public_key_sel.selection is {selection}, expected 0 "
            f"(PUBK_SEL_ROM_KEY): the index bound is only reached on the ROM-key "
            f"arm (manifest_crypto.c:170)"
        )
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-KEY-INDEX: backup public_key_sel=0x%04x (ROM key source, "
            "index %d == PUBK_SEL_NUM_ROM_KEYS, the smallest out-of-range value), "
            "TBS re-hashed", got, _BAD_INDEX,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"terminate the run first"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: this testcase "
            f"forbids the fuse echo to prove the index bound ran first, so the "
            f"bitmap must be clear for that forbid to be meaningful"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        assert any(_PUBK_SEL_ECHO in line for line in console), (
            f"ROM never printed {_PUBK_SEL_ECHO}: the BAD_KEY_IDX verdict cannot "
            f"be attributed to the index this testcase planted. Console: {console}"
        )
        n = sum(1 for line in console if "BAD_KEY_IDX" in line)
        assert n == 1, (
            f"BAD_KEY_IDX appeared {n} times, expected exactly 1 (the backup's). "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-KEY-INDEX-ECHO: ROM read %s and refused it once, without "
            "consulting the revocation bitmap", _PUBK_SEL_ECHO,
        )
