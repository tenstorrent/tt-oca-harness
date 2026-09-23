# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boot the production ROM over the OpenTitan SPI host with the SECURE_DMA RX drain.

``+sep_boot_from_spi`` selects the SPI branch; without it the ROM boots from SMC SRAM.
Subclasses override the flash image, the markers and the transport hooks.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# Raw binary: the .spi_preload file is $readmemh text, which preload() cannot read.
_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "non_secure_boot.bin")
SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "secure_boot.bin")

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 24_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 50_000

_SPI_PATH_MARKER = "BOOT_SPI"
_SMC_PATH_MARKER = "WAIT_SMC_MANIFEST"
_MANIFEST_OK_MARKER = "MANIFEST_OK"
# Only the SPI branch prints a flash-relative offset; the SMC-SRAM branch prints 0x4006xxxx.
_MANIFEST_SRC_MARKER = "MANIFEST_SRC=0x00001000"


@pyuvm.test()
class sep_rom_ot_dma_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM with the manifest fetched over SPI."""

    build_env = False

    # Gate on the cold_scratch[0] verdict word; every subclass inherits this.
    verdict_source = "scratch0"
    flash_image = _FLASH_IMAGE
    required_markers = (_SPI_PATH_MARKER, _MANIFEST_SRC_MARKER, _MANIFEST_OK_MARKER)
    # Cannot fail once BOOT_SPI is seen; _MANIFEST_SRC_MARKER is the independent evidence.
    forbidden_markers = (_SMC_PATH_MARKER,)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def build_efuse_image(self):
        # To change LC_STATE use select_efuse_image(); an image built here is too late.
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        return buf

    def log_transport(self, flash) -> None:
        # Runs before the marker checks so the SPI history survives a failure; must not raise.
        ...

    def check_transport(self, console: list[str], flash) -> None:
        ...




    async def run_scenario(self) -> None:
        dut = cocotb.top
        # BL1 prints on the scratch console, not the mailbox console the banner check reads.
        self.sb.expected_line = ""
        # Real fuse sense runs, so the image must hold an LC_STATE the manifest allows.
        efuse_img = self.build_efuse_image()
        self.write_efuse_image(efuse_img)

        console: list[str] = []
        cocotb.start_soon(rom_console_task(self.logger, sink=console))

        flash = OcahSpiFlash(
            dut.spi_cs_n_o,
            dut.spi_sck_o,
            mosi=dut.spi_mosi_o,
            miso=dut.spi_miso_i,
            name="sep_rom_boot_flash",
        )
        # At flash address 0 the image puts both manifests and the payload at the ROM's offsets.
        with open(self.flash_image, "rb") as fh:
            image = bytearray(fh.read())
        loaded = bytes(self.mutate_flash_image(image))
        # The slot-address checks need the post-mutation length, not the on-disk one.
        self._image_len = len(loaded)
        flash.preload(loaded)
        await flash.start()
        try:
            # No TCM backdoor load, so ICCM ECC is valid only where the ROM loads BL1.
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            await self.poll_boot(
                self.sb,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            await flash.stop()
            self.log_transport(flash)
            log_scratch_cold(self.logger)

        # fw_pass cannot tell the manifest sources apart, so require the path markers.
        assert self.required_markers, (
            "required_markers is empty -- the marker checks below would pass vacuously"
        )
        assert console, (
            "ROM console is empty: the virt-console decoder produced no lines, so no "
            "marker check below means anything"
        )
        for marker in self.required_markers:
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}. Console: {console}"
            )
            self.logger.info("CHK-ROM-PATH: required marker observed: %s", marker)
        for marker in self.forbidden_markers:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which means it did not take the intended "
                f"path. Console: {console}"
            )

        self.check_transport(console, flash)

