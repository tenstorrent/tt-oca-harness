# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary holds 0x5A at an unselected package_id byte; the backup boots.

``boot-manifest.adoc`` requires an unselected identity byte to be MANIFEST_UNUSED_BYTE, so
``oca_check_identity`` refuses the primary with ``OCA_FAIL_PACKAGE_ID`` before key selection.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw.sep_backup_manifest_structural_fail_base import err_marker
from rom_fw.sep_usage_constraint_base import (
    MANIFEST_ERR_PACKAGE_ID,
    sep_primary_usage_constraint_base,
)

_KIND = "package"
_BYTE = 5
_VALUE = 0x5A


@pyuvm.test()
class sep_firmware_manifest_primary_unselected_identity_byte_test(
    sep_primary_usage_constraint_base
):
    """Primary package_id byte 5 is 0x5A with no package selector bit -> refused."""

    primary_expected_error = MANIFEST_ERR_PACKAGE_ID
    primary_defect_marker = err_marker(MANIFEST_ERR_PACKAGE_ID)

    def plant(self, buf: bytearray, slot: str) -> None:
        golden = bytes(buf)
        sel = mm.selector_bits(buf, slot)
        assert sel == mm.SHIPPED_SELECTOR_BITS and not sel & mm.selector_mask(_KIND, _BYTE), (
            f"{slot} selector_bits is 0x{sel:x}: {_KIND} byte {_BYTE} must be unselected "
            f"in the shipped 0x{mm.SHIPPED_SELECTOR_BITS:x}"
        )
        mm.verify_identity_layout(buf, slot)
        others = {k: mm.identity(buf, slot, k) for k in mm.OFF_IDENTITY if k != _KIND}

        # set_identity forces 0xA5 into unselected bytes, so write the byte directly.
        at = mm.OFF_IDENTITY[_KIND] + _BYTE
        buf[mm.slot_base(slot) + at] = _VALUE
        pm.reseal(buf, slot, check_toc=not pm.is_encrypted(buf, slot))
        pm.verify_sealed(buf, slot)
        mm.verify_public_key(buf, slot)

        field = mm.identity(buf, slot, _KIND)
        stray = [i for i in range(mm.IDENTITY_LEN) if field[i] != mm.SHIPPED_IDENTITY_BYTE]
        assert stray == [_BYTE] and field[_BYTE] == _VALUE, (
            f"{slot} {_KIND} identity {field.hex()} has non-0x{mm.SHIPPED_IDENTITY_BYTE:02x} "
            f"bytes at {stray}, expected only byte {_BYTE} = 0x{_VALUE:02x}"
        )
        assert mm.selector_bits(buf, slot) == sel, f"{slot} selector_bits changed"
        for k, before in others.items():
            assert mm.identity(buf, slot, k) == before, f"{slot} {k} identity changed"

        base = mm.slot_base(slot)
        seals = set(range(mm.OFF_MANIFEST_HASH, mm.OFF_MANIFEST_HASH + mm.HASH_FIELD_SIZE))
        seals |= set(range(mm.OFF_SIGNATURE, mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES))
        changed = {i for i in range(mm.BODY_SIZE) if golden[base + i] != buf[base + i]}
        assert at in changed and changed - {at} <= seals, (
            f"{slot} manifest bytes {sorted(changed - {at} - seals)[:16]} changed outside "
            f"{_KIND} byte {_BYTE}, manifest_hash and the signature"
        )
        plain = pm.plaintext_diff(golden, bytes(buf), slot)
        assert plain == [], f"{slot} cleartext payload changed at {plain}"

        self.record_identity(buf, slot, _KIND)
        self.logger.info(
            "CHK-STIMULUS-UNSELECTED-ID: %s %s byte %d = 0x%02x with selector_bits 0x%x "
            "(byte unselected); every other identity byte holds 0x%02x, the payload is "
            "unchanged and the slot is re-sealed and re-signed",
            slot,
            _KIND,
            _BYTE,
            _VALUE,
            sel,
            mm.SHIPPED_IDENTITY_BYTE,
        )
