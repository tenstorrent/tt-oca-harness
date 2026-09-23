# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names ROM key index 6, outside the table; the backup boots.

The ROM must refuse the index with ``BAD_KEY_IDX`` before it reads the revocation
bitmap, because ``1u << index`` for an index of 6 or more names no ROM slot.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_SIG_FAILED,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BAD_INDEX = mm.PUBK_SEL_NUM_ROM_KEYS
# public_key_sel is {index:4, selection:3}; PUBK_SEL_ROM_KEY is 0.
_BAD_PUBK_SEL_VALUE = _BAD_INDEX & 0xF
_PRIMARY_SEL_ECHO = f"PUBK_SEL=0x{_BAD_PUBK_SEL_VALUE:08x}"
# The shipped backup selects ROM key slot 0.
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"
_REVOKE_ECHO = "PUBK_REVOKE="


@pyuvm.test()
class sep_firmware_primary_rom_key_index_invalid_test(
        sep_primary_fail_backup_boot_base):
    """Primary names ROM key index 6 -> rejected at the bound -> backup boots."""

    primary_defect_marker = "BAD_KEY_IDX"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    # The index bound precedes rsa_3072_verify, so the primary never drives it.
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_PRIMARY_SEL_ECHO, _BACKUP_SEL_ECHO)
    # ROM_KEY_EMPTY here would mean index 6 read past the six-entry digest table.
    extra_forbidden = ("BAD_KEY_SEL", "ROM_KEY_EMPTY", "PUBK_HASH_MISMATCH",
                       "KEY_REVOKED", "FUSE_KEY_EMPTY", "VERSION_ROLLBACK",
                       "BAD_SIG_TYPE=", "RSA_VERIFY_FAIL")

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.set_public_key_sel(buf, "primary", selection=0, index=_BAD_INDEX)
        got = mm.get_public_key_sel(buf, "primary")
        assert got == _BAD_PUBK_SEL_VALUE, (
            f"primary public_key_sel encoded as 0x{got:04x}, expected "
            f"0x{_BAD_PUBK_SEL_VALUE:04x} (selection=PUBK_SEL_ROM_KEY, "
            f"index={_BAD_INDEX})"
        )
        selection = (got >> 4) & 0x7
        assert selection == 0, (
            f"public_key_sel.selection is {selection}, expected 0 "
            f"(PUBK_SEL_ROM_KEY): the index bound is only reached on the ROM-key "
            f"arm (manifest_crypto.c:170)"
        )
        # A bad TBS hash would refuse the primary before key selection.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-KEY-INDEX: primary public_key_sel=0x%04x (ROM key source, "
            "index %d == PUBK_SEL_NUM_ROM_KEYS, the smallest out-of-range value), "
            "TBS re-hashed, magic intact so the slot still reaches "
            "validate_signature", got, _BAD_INDEX,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"reject the primary for a different reason"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: this testcase pins "
            f"the fuse echo to the BACKUP's single occurrence to prove the index "
            f"bound ran first, so the bitmap must be clear -- and the backup "
            f"selects ROM slot 0 and must be able to use it or nothing would boot"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psel = index_of(_PRIMARY_SEL_ECHO)
        i_bad = index_of("BAD_KEY_IDX")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)

        assert 0 <= i_psel < i_bad < i_bsrc, (
            f"the BAD_KEY_IDX verdict is not attributable to the primary's planted "
            f"index: {_PRIMARY_SEL_ECHO}@{i_psel} -> BAD_KEY_IDX@{i_bad} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        n_bad = sum(1 for line in console if "BAD_KEY_IDX" in line)
        assert n_bad == 1, (
            f"BAD_KEY_IDX appeared {n_bad} times, expected exactly 1 (the "
            f"primary's); the backup must not carry this defect. Console: {console}"
        )

        n_revoke = sum(1 for line in console if _REVOKE_ECHO in line)
        assert n_revoke == 1, (
            f"{_REVOKE_ECHO} appeared {n_revoke} times, expected exactly 1 (the "
            f"backup's). More than one means the primary reached "
            f"check_pubkey_revoked (manifest_crypto.c:181), so the index bound at "
            f":174-177 did not preempt it. Console: {console}"
        )
        assert i_bsrc < i_revoke, (
            f"{_REVOKE_ECHO}@{i_revoke} did not follow the backup read@{i_bsrc}: "
            f"the single fuse echo is the primary's, so the bound did not stop it. "
            f"Console: {console}"
        )
        assert i_bsrc < i_bsel < i_revoke, (
            f"the booting slot's key selection is unattributed: backup@{i_bsrc} -> "
            f"{_BACKUP_SEL_ECHO}@{i_bsel} -> {_REVOKE_ECHO}@{i_revoke}. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-BOUND-PREEMPTS-REVOKE: primary %s@%d -> BAD_KEY_IDX@%d with no "
            "fuse echo, then backup@%d -> %s@%d -> %s@%d -> boot",
            _PRIMARY_SEL_ECHO, i_psel, i_bad, i_bsrc, _BACKUP_SEL_ECHO, i_bsel,
            _REVOKE_ECHO, i_revoke,
        )
