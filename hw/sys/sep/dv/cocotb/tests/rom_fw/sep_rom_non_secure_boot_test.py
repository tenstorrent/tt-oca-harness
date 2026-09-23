# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot VeeR EL2 from the production Boot ROM on the non-SPI (SMC-SRAM) manifest path.

Without ``+sep_boot_from_spi`` the ROM skips the SPI host, and a behavioural SMC
responder supplies the manifest and BL1.
"""

from __future__ import annotations

from sep_reg_meta import sym

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from sep_base_test import sep_base_test
from sep_reg_meta import sym

# rst_vec carries PC[31:1], so bring-up passes this base shifted right by one.
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 4_000_000

# BL1 and FUSE_CHK exist only in BL1 and prove handoff; nothing here tests hash rejection.
_REQUIRED_ROM_MARKERS = (
    "COLD",
    "MANIFEST_HASH_OK",
    "PLD_HASH_OK",
    "BL1",
    "FUSE_CHK",
)
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 5_000


@pyuvm.test()
class sep_rom_non_secure_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM and hand off to BL1 (SMC-SRAM path)."""

    build_env = False

    # Gate on the cold_scratch[0] verdict word; every subclass inherits this.
    verdict_source = "scratch0"

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # BL1 prints on the scratch console, not the mailbox console the banner check reads.
        self.sb.expected_line = ""
        self._rom_markers: list[str] = []
        # Real fuse sense runs, so LC_STATE must be one the manifest allows (TEST_DEV is).
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)
        cocotb.start_soon(rom_console_task(self.logger, sink=self._rom_markers))
        try:
            # No TCM backdoor load, so ICCM ECC is valid only where the ROM loads BL1.
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            await self.poll_boot(
                self.sb,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
            # The PASS gate ignores the console, so a dark console would still pass.
            missing = [m for m in _REQUIRED_ROM_MARKERS if m not in self._rom_markers]
            assert not missing, (
                f"ROM/BL1 stage markers missing from the scratch console: {missing}; "
                f"saw {self._rom_markers}"
            )
            self.logger.info(
                "CHK-ROM-STAGES PASS: all %d required ROM/BL1 stage markers observed (%s)",
                len(_REQUIRED_ROM_MARKERS),
                ", ".join(_REQUIRED_ROM_MARKERS),
            )
        finally:
            log_scratch_cold(self.logger)
