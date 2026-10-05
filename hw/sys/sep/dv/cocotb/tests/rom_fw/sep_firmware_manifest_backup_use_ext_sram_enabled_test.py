# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unsupported backup-set payload-destination scaffold.

The OCA manifest has no payload-destination selector, the ROM stages payloads into SEP
SRAM, and shared payload helpers reject ``smc=True`` and ``stage_in_smc``. This file
defines primary-refusal, backup-set, and SEP-marker geometry.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002

_REQUIRED, _FORBIDDEN = ues.sep_markers()


@pyuvm.test()
class sep_firmware_manifest_backup_use_ext_sram_enabled_test(sep_primary_fail_backup_boot_base):
    """Primary-refusal and backup-set marker scaffold."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    extra_required = _REQUIRED
    extra_forbidden = _FORBIDDEN

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.set_identifier(buf, "primary")

    def prepare_backup(self, buf: bytearray) -> None:
        ues.assert_stimulus(self.logger, buf, "backup", want_set=True)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        ues.assert_destination(self.logger, console, expect_smc=False)
