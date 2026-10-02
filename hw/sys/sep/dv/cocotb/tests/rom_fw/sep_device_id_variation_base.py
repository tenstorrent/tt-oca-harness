# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-byte ``selector_bits`` variation for one identity kind.

A ROM that checked only the lowest selected byte would accept the primary; one that
ignored the selector would refuse the backup.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_CHIPLET_ID,
    MANIFEST_ERR_PACKAGE_ID,
    sep_primary_usage_constraint_base,
)

_ERROR = {"chiplet": MANIFEST_ERR_CHIPLET_ID, "package": MANIFEST_ERR_PACKAGE_ID}
# The backup leaves this byte unselected, so its 0xA5 fill must be ignored.
_BACKUP_UNSELECTED = 0


class sep_device_id_variation_base(sep_primary_usage_constraint_base):
    kind: str = ""
    # Selected and equal to the fuse.
    match_byte: int = -1
    # Selected, differs from the fuse, above match_byte.
    mismatch_byte: int = -1

    def __init_subclass__(cls, **kwargs) -> None:
        if cls.kind:
            assert cls.kind in _ERROR, f"{cls.__name__}: kind must be one of {sorted(_ERROR)}"
            assert 0 < cls.match_byte < cls.mismatch_byte < mm.IDENTITY_LEN, (
                f"{cls.__name__}: need 0 < match_byte < mismatch_byte < {mm.IDENTITY_LEN}, "
                f"so an unselected byte sits below both and the mismatch is not the "
                f"lowest selected byte"
            )
            cls.primary_expected_error = _ERROR[cls.kind]
            cls.primary_defect_marker = err_marker(_ERROR[cls.kind])
        super().__init_subclass__(**kwargs)

    def plant(self, buf: bytearray, slot: str) -> None:
        self.plant_identity(
            buf, slot, self.kind, mismatch=(self.mismatch_byte,), match=(self.match_byte,)
        )

    def prepare_backup(self, buf: bytearray) -> None:
        fuse = self._fuse_id[self.kind]
        assert fuse[_BACKUP_UNSELECTED] != mm.SHIPPED_IDENTITY_BYTE, (
            f"{self.kind} fuse byte {_BACKUP_UNSELECTED} is 0x{mm.SHIPPED_IDENTITY_BYTE:02x}, "
            f"the same as the unselected fill, so the backup would not show that an "
            f"unselected byte is ignored"
        )
        selected = tuple(i for i in range(mm.IDENTITY_LEN) if i != _BACKUP_UNSELECTED)
        mask = 0
        for i in selected:
            mask |= mm.selector_mask(self.kind, i)
        mm.set_identity(buf, "backup", self.kind, fuse, mask)
        sel = mm.selector_bits(buf, "backup")
        assert sel == mask, f"backup selector_bits is 0x{sel:x}, expected exactly 0x{mask:x}"
        self.record_identity(buf, "backup", self.kind)
        self.logger.info(
            "CHK-STIMULUS-BACKUP-IDENTITY: backup selects %s bytes 1..%d equal to the fuse "
            "(selector_bits 0x%x); byte %d is unselected and holds 0x%02x against fuse 0x%02x",
            self.kind,
            mm.IDENTITY_LEN - 1,
            sel,
            _BACKUP_UNSELECTED,
            mm.identity(buf, "backup", self.kind)[_BACKUP_UNSELECTED],
            fuse[_BACKUP_UNSELECTED],
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        self.logger.info(
            "CHK-PER-BYTE-VARIATION PASS: primary refused 0x%08x with %s byte %d selected "
            "and equal to the fuse and byte %d selected and different; the backup "
            "selected %d bytes equal to the fuse with byte %d unselected and different, "
            "and booted",
            self.primary_expected_error,
            self.kind,
            self.match_byte,
            self.mismatch_byte,
            mm.IDENTITY_LEN - 1,
            _BACKUP_UNSELECTED,
        )
