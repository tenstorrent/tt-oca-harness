# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_rom_boot_min_pass_test - toolchain-free SMC ROM boot on the wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_rom_boot_min_pass_seq import SmuSmcRomBootMinPassSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_rom_boot_min_pass_test(smu_base_test):
    """SMC CPU executes the checked-in ROM stub and lands its magic in scratch0."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_rom_boot_min_pass_test SEP=1 "
            "SMC ROM boot from hw/sys/smc/dv/assets/min_pass.rom.hex"
        )
        await SmuSmcRomBootMinPassSeq(self).run()
