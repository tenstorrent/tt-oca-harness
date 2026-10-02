# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup payload declares no SEP_BL1 image; with both slots refused the ROM halts.

The primary fails the package identity check (``OCA_FAIL_PACKAGE_ID``). The backup reaches
``PAYLOAD_OK`` and fails only the BL1-presence check (``OCA_BOOT_ERR_NO_BL1``).
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import err_marker, sep_backup_payload_fail_base

_MANIFEST_ERR_PACKAGE_ID = mm.boot_err("OCA_FAIL_PACKAGE_ID")
_NO_BL1 = "NO_BL1_IMAGE"
_RELABEL_TYPE = pm.IMAGE_TYPE_SEP_BL2
_REJECT_BYTE = 1


@pyuvm.test()
class sep_firmware_manifest_backup_missing_sepbl1_test(sep_backup_payload_fail_base):
    """Backup TOC declares SEPBL2 where BL1 was -> both slots refused -> halt."""

    backup_defect_marker = _NO_BL1
    expected_error = pm.MANIFEST_ERR_NO_BL1
    backup_expected_stage = "placement"
    backup_ordered = ("PAYLOAD_OK",)
    backup_absent = ("DECRYPT_OK",)
    primary_expected_error = _MANIFEST_ERR_PACKAGE_ID
    # Identity is checked after the body is read and before key selection.
    primary_ordered = ("OCA_BODY=", "MFST_VER=", err_marker(_MANIFEST_ERR_PACKAGE_ID))
    primary_absent = ("PUBK_SEL=", "PUBK_AUTHORIZED", "MANIFEST_OK")
    efuse_preload = td.PLAINTEXT_EFUSE

    def check_efuse(self, image) -> None:
        # corrupt_primary() reads self._fuse_byte; run_scenario calls check_efuse() first.
        fd.assert_clean_key_fuses(image)
        sip = image.field_int("SEP_SIP_ID").to_bytes(mm.IDENTITY_LEN, "little")
        self._fuse_byte = sip[_REJECT_BYTE]

    def corrupt_primary(self, buf: bytearray) -> None:
        value = bytearray(mm.identity(buf, "primary", "package"))
        value[_REJECT_BYTE] = self._fuse_byte ^ 0xFF
        mm.set_identity(
            buf, "primary", "package", bytes(value), mm.selector_mask("package", _REJECT_BYTE)
        )
        self._primary_served = mm.identity(buf, "primary", "package")
        assert self._primary_served[_REJECT_BYTE] != self._fuse_byte, (
            f"planted package identity byte 0x{self._primary_served[_REJECT_BYTE]:02x} "
            f"still matches fuse SEP_SIP_ID byte 0x{self._fuse_byte:02x}; the mutation "
            f"did not change the byte the ROM's selector reads"
        )
        self.logger.info(
            "CHK-STIMULUS-TRIGGER: primary selects package identity byte %d = 0x%02x "
            "against fuse SEP_SIP_ID byte 0x%02x, so the ROM must refuse it with "
            "MANIFEST_ERR=0x%08x before key selection",
            _REJECT_BYTE,
            self._primary_served[_REJECT_BYTE],
            self._fuse_byte,
            _MANIFEST_ERR_PACKAGE_ID,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        golden = bytes(buf)
        entry = pm.find_image(buf, "backup")
        before = pm.entry_type(buf, entry)
        assert before == pm.IMAGE_TYPE_SEP_BL1, (
            f"backup TOC BL1 entry type is {before!r}, expected "
            f"{pm.IMAGE_TYPE_SEP_BL1!r}: the shipped image is not the valid "
            f"baseline this testcase relabels away from"
        )
        self.logger.info("CHK-STIMULUS-BL1-BEFORE: %s", pm.describe_bl1(buf, "backup"))
        changed = pm.retype_bl1_image(buf, "backup", _RELABEL_TYPE)
        assert changed == before
        types = [pm.entry_type(buf, e) for e in pm.toc_entries(buf, "backup")]
        assert pm.IMAGE_TYPE_SEP_BL1 not in types, (
            f"backup TOC still declares a SEP_BL1 image: {types}"
        )
        rules = pm.spec_rule_violations(buf, "backup")
        assert rules == [], f"the relabelled backup TOC also breaks spec rules {rules}"
        type_at = entry - pm.payload_base(buf, "backup") + pm.E_TYPE
        changed = {i for r in pm.plaintext_diff(golden, bytes(buf), "backup") for i in r}
        assert changed and changed <= set(range(type_at, type_at + 16)), (
            f"the relabel changed cleartext bytes {sorted(changed)[:16]} outside the entry "
            f"type at payload offset {type_at}"
        )
        # The backup must pass both library stages so that only the BL1 check refuses it.
        pm.verify_sealed(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-MISSING-BL1: backup TOC entry @0x%x relabelled "
            "%r -> %r, leaving types %s and no SEP_BL1; the slot is re-sealed "
            "and its modulus still hashes to the ROM's slot digest",
            entry,
            before,
            _RELABEL_TYPE,
            types,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        fd.assert_served_field(
            self.logger,
            self._flash,
            "primary",
            mm.OFF_IDENTITY["package"],
            self._primary_served,
            "primary package identity",
        )
