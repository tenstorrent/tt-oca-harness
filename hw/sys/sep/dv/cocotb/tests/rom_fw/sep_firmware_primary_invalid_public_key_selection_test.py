# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names an unassigned public-key source; the backup boots.

Only the primary's key selection is broken, so it reaches that check and fails BAD_KEY_SEL.
Needs ``+sep_crypto_edn_force``: OTBN waits for EDN entropy in the backup's RSA-3072 verify.
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

# manifest.h assigns 0, 1, 2, 4, 5. 3, 6 and 7 name nothing.
_BAD_SELECTION = 3
# public_key_sel is {index:4, selection:3} -- index 0, selection 3 -> 0x0030.
_BAD_PUBK_SEL_VALUE = (_BAD_SELECTION & 0x7) << 4
_PRIMARY_SEL_ECHO = f"PUBK_SEL=0x{_BAD_PUBK_SEL_VALUE:08x}"
# The backup keeps the shipped selector: ROM key slot 0.
_BACKUP_SEL_ECHO = "PUBK_SEL=0x00000000"


@pyuvm.test()
class sep_firmware_primary_invalid_public_key_selection_test(
        sep_primary_fail_backup_boot_base):
    """Primary names key source 3 -> rejected -> backup boots."""

    primary_defect_marker = "BAD_KEY_SEL"
    primary_expected_error = MANIFEST_ERR_SIG_FAILED
    efuse_preload = _EFUSE_PRELOAD
    extra_required = (_PRIMARY_SEL_ECHO, _BACKUP_SEL_ECHO)
    # BAD_KEY_IDX shares this error code, so forbid it to separate the two arms.
    extra_forbidden = ("BAD_KEY_IDX", "BAD_SIG_TYPE=", "ROM_KEY_EMPTY",
                       "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "KEY_REVOKED",
                       "VERSION_ROLLBACK", "RSA_VERIFY_FAIL")

    def corrupt_primary(self, buf: bytearray) -> None:
        # No manifest_identifier corruption: the primary must reach key selection.
        mm.set_public_key_sel(buf, "primary", selection=_BAD_SELECTION, index=0)
        got = mm.get_public_key_sel(buf, "primary")
        assert got == _BAD_PUBK_SEL_VALUE, (
            f"primary public_key_sel encoded as 0x{got:04x}, expected "
            f"0x{_BAD_PUBK_SEL_VALUE:04x} (index 0, selection {_BAD_SELECTION})"
        )
        # A stale TBS hash would reject the primary before key selection.
        mm.verify_layout(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PUBKSEL: primary public_key_sel=0x%04x (selection=%d, "
            "unassigned; index 0 unchanged), TBS re-hashed, magic intact so the "
            "slot still reaches validate_signature", got, _BAD_SELECTION,
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
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: the backup selects "
            f"ROM slot 0 and must be able to use it, or nothing would boot"
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psel = index_of(_PRIMARY_SEL_ECHO)
        i_bad = index_of("BAD_KEY_SEL")
        i_bsrc = index_of(f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}")
        i_bsel = index_of(_BACKUP_SEL_ECHO)

        assert 0 <= i_psel < i_bad < i_bsrc, (
            f"the BAD_KEY_SEL verdict is not attributable to the primary's planted "
            f"selector: {_PRIMARY_SEL_ECHO}@{i_psel} -> BAD_KEY_SEL@{i_bad} -> "
            f"backup@{i_bsrc}. Console: {console}"
        )
        assert i_bsrc < i_bsel, (
            f"{_BACKUP_SEL_ECHO}@{i_bsel} did not follow the backup read@{i_bsrc}: "
            f"the booting slot's key selection is unattributed. Console: {console}"
        )
        self.logger.info(
            "CHK-PUBKSEL-FAILOVER: primary %s@%d -> BAD_KEY_SEL@%d -> backup@%d "
            "-> %s@%d", _PRIMARY_SEL_ECHO, i_psel, i_bad, i_bsrc,
            _BACKUP_SEL_ECHO, i_bsel,
        )
