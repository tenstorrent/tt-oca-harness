# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup's SEP_BL1 is not its first TOC image; the backup still boots.

The primary fails the package identity check; the backup stores BLMEMMAP and _VENDOR1
ahead of SEP_BL1, so the ROM must find BL1 by type. Needs ``+esrc_noise_force``.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import err_marker
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base
from rom_fw.sep_toc_order_boot_base import bl1_index, copy_src

_MANIFEST_ERR_PACKAGE_ID = mm.boot_err("OCA_FAIL_PACKAGE_ID")
_REJECT_BYTE = 1


@pyuvm.test()
class sep_firmware_manifest_backup_reordered_sepbl1_test(sep_primary_fail_backup_boot_base):
    """Primary refused on package identity; the backup's BL1 sits at TOC index 2 and boots."""

    flash_image = td.MULTI_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = _MANIFEST_ERR_PACKAGE_ID
    primary_defect_marker = err_marker(_MANIFEST_ERR_PACKAGE_ID)
    # Identity is checked after the body is read and before key selection.
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ("PUBK_SEL=", "PUBK_AUTHORIZED", "MANIFEST_OK")
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

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
            f"still matches fuse SEP_SIP_ID byte 0x{self._fuse_byte:02x}"
        )

    def prepare_backup(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "backup"), f"{self.flash_image} backup is encrypted"
        index = bl1_index(buf, "backup")
        assert index > 0, "backup SEP_BL1 is TOC entry 0, so the run would not show a search"
        assert pm.spec_rule_violations(buf, "backup") == []
        self._copy_src = copy_src(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-REORDER: backup TOC left as packed with SEP_BL1 at index %d, so "
            "the ROM must copy BL1 from 0x%08x",
            index,
            self._copy_src,
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        backup = oc.split_attempts(console)[1]
        want = f"COPY_SRC=0x{self._copy_src:08x}"
        oc.assert_attempt(
            backup,
            error=None,
            stage="accepted",
            ordered=("PAYLOAD_OK", want, "BL1_COPIED", "BL1_JUMP="),
        )
        assert oc.count(console, "COPY_SRC=") == 1, f"COPY_SRC= printed more than once: {console}"
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            mm.OFF_IDENTITY["package"],
            self._primary_served,
            "primary package identity",
        )
        self.logger.info("CHK-BL1-BY-TYPE PASS: backup accepted and copied BL1 from %s", want)
