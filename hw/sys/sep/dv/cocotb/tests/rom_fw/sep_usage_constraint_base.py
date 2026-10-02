# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary and backup bases for usage-constraint refusals: fail over, or halt.

The identity and lifecycle checks print no marker, so each member names its error line;
the refused attempt prints ``OCA_BODY=`` and ``MFST_VER=`` and no key-selection marker.
"""

from __future__ import annotations

from pathlib import Path

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

MANIFEST_ERR_CHIPLET_ID = mm.boot_err("OCA_FAIL_CHIPLET_ID")
MANIFEST_ERR_PACKAGE_ID = mm.boot_err("OCA_FAIL_PACKAGE_ID")
MANIFEST_ERR_SYSTEM_ID = mm.boot_err("OCA_FAIL_SYSTEM_ID")
MANIFEST_ERR_LIFECYCLE = mm.boot_err("OCA_FAIL_LIFECYCLE")
MANIFEST_ERR_CALLBACK_UNAVAILABLE = mm.boot_err("OCA_FAIL_CALLBACK_UNAVAILABLE")

EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

FUSE_IDENTITY_FIELD = {"chiplet": "SEP_CHIPLET_ID", "package": "SEP_SIP_ID", "system": "SEP_SYS_ID"}

LIVE_LC_BIT = mm.LIFECYCLE_STATE_BITS["PROD"]
LC_ALLOWED_WITHOUT_LIVE = mm.LIFECYCLE_STATES_VALID_MASK & ~(1 << LIVE_LC_BIT)

_BODY_MARKERS = ("OCA_BODY=", "MFST_VER=")
# Key selection runs after the usage constraints, so a refused slot prints none of these.
_KEY_MARKERS = ("PUBK_SEL=", "PUBK_AUTHORIZED", "PUBK_REVOKE=", "FUSE_VER=")


def fuse_identity(image, kind: str) -> bytes:
    return image.field_int(FUSE_IDENTITY_FIELD[kind]).to_bytes(mm.IDENTITY_LEN, "little")


class _usage_constraint_mixin:
    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
        lc = image.lc_raw()
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}: LIVE_LC_BIT and LC_ALLOWED_WITHOUT_LIVE are "
            f"derived from PROD, so a different lifecycle breaks the lifecycle stimulus"
        )
        self._fuse_id = {kind: fuse_identity(image, kind) for kind in FUSE_IDENTITY_FIELD}

    def plant(self, buf: bytearray, slot: str) -> None:
        raise NotImplementedError

    def plant_identity(
        self,
        buf: bytearray,
        slot: str,
        kind: str,
        *,
        mismatch: tuple[int, ...],
        match: tuple[int, ...] = (),
    ) -> int:
        assert mismatch and not set(mismatch) & set(match), (
            f"mismatch {mismatch} must be non-empty and disjoint from match {match}"
        )
        fuse = self._fuse_id[kind]
        value = bytes(fuse[i] ^ 0xFF if i in mismatch else fuse[i] for i in range(mm.IDENTITY_LEN))
        mask = 0
        for i in mismatch + match:
            mask |= mm.selector_mask(kind, i)
        before = mm.selector_bits(buf, slot)
        assert before == mm.SHIPPED_SELECTOR_BITS, (
            f"{slot} selector_bits is 0x{before:x} before the write, expected the shipped "
            f"0x{mm.SHIPPED_SELECTOR_BITS:x}: another constraint would share the slot"
        )
        mm.set_identity(buf, slot, kind, value, mask)
        sel = mm.selector_bits(buf, slot)
        assert sel == mask, (
            f"{slot} selector_bits is 0x{sel:x}, expected exactly 0x{mask:x}: the "
            f"{kind} bytes {sorted(mismatch + match)} must be the slot's only constraint"
        )
        field = mm.identity(buf, slot, kind)
        wrong = [i for i in mismatch if field[i] == fuse[i]] + [
            i for i in match if field[i] != fuse[i]
        ]
        assert not wrong, (
            f"{slot} {kind} bytes {wrong} do not hold the planted relation to fuse "
            f"{fuse.hex()}: field {field.hex()}"
        )
        self.record_identity(buf, slot, kind)
        self.logger.info(
            "CHK-STIMULUS-IDENTITY: %s selects %s bytes %s (selector_bits 0x%x); bytes %s "
            "differ from %s %s, bytes %s equal it, and every unselected byte holds 0x%02x",
            slot,
            kind,
            sorted(mismatch + match),
            sel,
            list(mismatch),
            FUSE_IDENTITY_FIELD[kind],
            fuse.hex(),
            list(match),
            mm.SHIPPED_IDENTITY_BYTE,
        )
        return mask

    def plant_lifecycle(self, buf: bytearray, slot: str, allowed: int, level: str) -> None:
        before = mm.selector_bits(buf, slot)
        assert before == mm.SHIPPED_SELECTOR_BITS, (
            f"{slot} selector_bits is 0x{before:x} before the write, expected the shipped "
            f"0x{mm.SHIPPED_SELECTOR_BITS:x}: another constraint would share the slot"
        )
        mm.set_lifecycle_constraint(buf, slot, allowed, level)
        sel = mm.selector_bits(buf, slot)
        bit = mm.SELECTOR_BIT_LIFECYCLE[level]
        assert sel == 1 << bit, (
            f"{slot} selector_bits is 0x{sel:x}, expected only bit {bit} ({level} lifecycle)"
        )
        got = mm.lifecycle_states(buf, slot, level)
        assert got == allowed, (
            f"{slot} {level} lifecycle_states reads 0x{got:08x}, expected 0x{allowed:08x}"
        )
        self.record_served(
            buf, slot, mm.OFF_SELECTOR_BITS, mm.SELECTOR_BITS_LEN, f"{slot} selector_bits"
        )
        self.record_served(
            buf,
            slot,
            mm.OFF_LIFECYCLE_STATES[level],
            4,
            f"{slot} {level} lifecycle_states",
        )
        self.logger.info(
            "CHK-STIMULUS-LIFECYCLE: %s selects the %s lifecycle (selector bit %d) "
            "permitting 0x%08x; the live token is bit %d (PROD)",
            slot,
            level,
            bit,
            allowed,
            LIVE_LC_BIT,
        )

    def record_served(self, buf: bytes, slot: str, offset: int, length: int, what: str) -> None:
        base = mm.slot_base(slot) + offset
        self._served_fields = getattr(self, "_served_fields", []) + [
            (slot, offset, bytes(buf[base : base + length]), what)
        ]

    def record_identity(self, buf: bytes, slot: str, kind: str) -> None:
        self.record_served(
            buf, slot, mm.OFF_SELECTOR_BITS, mm.SELECTOR_BITS_LEN, f"{slot} selector_bits"
        )
        self.record_served(
            buf, slot, mm.OFF_IDENTITY[kind], mm.IDENTITY_LEN, f"{slot} {kind} identity"
        )

    def check_served(self, flash) -> None:
        fields = getattr(self, "_served_fields", [])
        assert fields, "plant() recorded no field, so the device record checks nothing"
        for slot, offset, want, what in fields:
            fd.assert_served_field(self.logger, flash, slot, offset, want, what)


class sep_primary_usage_constraint_base(_usage_constraint_mixin, sep_primary_fail_backup_boot_base):
    primary_expected_rsa_starts = 0
    primary_expected_stage = "manifest"
    primary_ordered = _BODY_MARKERS
    primary_absent = _KEY_MARKERS
    efuse_preload = EFUSE_PRELOAD

    def corrupt_primary(self, buf: bytearray) -> None:
        self.plant(buf, "primary")

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        self.check_served(flash)


class sep_backup_usage_constraint_base(
    _usage_constraint_mixin, sep_backup_manifest_structural_fail_base
):
    backup_ordered = _BODY_MARKERS
    efuse_preload = EFUSE_PRELOAD

    def corrupt_backup(self, buf: bytearray) -> None:
        self.plant(buf, "backup")

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        self.check_served(self._flash)
