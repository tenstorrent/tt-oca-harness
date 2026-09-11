# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup asks for SMC SRAM staging after the primary is refused.

On the failover path. The primary is rejected on its identifier, upstream
of the staging step, so it never stages. The backup has ``use_ext_sram`` cleared, so the
run's single staging event is the backup's and it must go through the SMC arm:
``EXT_SRAM_INIT_WAIT``, the scratch[13]/[14] window, then
``smc_sram_base + scratch[13]``.

This is the member that crosses the two dimensions the coverage plan asks for --
slot selection and staging destination -- so it is the one that would catch a
ROM that read the bit from the wrong slot. The primary still carries
``use_ext_sram=1`` from the shipped config, so a ROM that latched the primary's
value would stage in SEP SRAM and fail on the forbidden ``USING_SEP_SRAM``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# manifest.h: validate_manifest_header refuses a bad identifier with this.
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002

_REQUIRED, _FORBIDDEN = ues.smc_markers()


@pyuvm.test()
class sep_firmware_manifest_backup_use_ext_sram_disabled_test(
        sep_primary_fail_backup_boot_base):
    """Primary refused on its identifier; the backup stages in the SMC window."""

    efuse_preload = _EFUSE_PRELOAD
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    extra_required = _REQUIRED
    extra_forbidden = _FORBIDDEN

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.set_identifier(buf, "primary")
        # Left set deliberately: the two slots must disagree, so a ROM that read
        # the wrong slot's bit stages in the wrong place and trips the forbidden
        # USING_SEP_SRAM rather than passing.
        ues.assert_stimulus(self.logger, buf, "primary", want_set=True)

    def prepare_backup(self, buf: bytearray) -> None:
        mm.set_flag_args_bit(buf, "backup", mm.FLAG_ARGS_BIT_USE_EXT_SRAM, False)
        ues.assert_stimulus(self.logger, buf, "backup", want_set=False)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        ues.assert_destination(self.logger, console, expect_smc=True)
