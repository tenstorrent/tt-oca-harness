# SPDX-License-Identifier: Apache-2.0
"""SEP ROM boot over the OpenTitan SPI host, SECURE_DMA drain (PyUVM).

Sibling of ``sep_rom_non_secure_boot_test``. Same production Boot ROM, same BL1
payload, same PASS criteria -- but the manifest and payload are fetched over the
**real OpenTitan SPI host** from a flash device model, instead of being handed to
the ROM through the behavioral SMC-SRAM responder.

``dma`` in the name is load-bearing, not decoration. The OpenTitan controller can
drain its RX FIFO two ways, chosen at build time in ``boot_flash.h``: the
SECURE_DMA hardware handshake (``BOOT_OT_SPI_USE_PIO=0``, what this test builds)
or CPU programmed I/O (``=1``, ``build_ot_pio/``). They are different datapaths
reading the same bytes, so a passing DMA boot says nothing about the PIO one.
The PIO variant has no test here yet -- the Makefile can build it
(``ot-pio-toolchain-images``) but nothing exercises it, so treat that path as
unverified rather than covered. The reference flow keeps them as a named pair
(``sep_rom_ot_dma_boot_test`` / ``sep_rom_ot_pio_boot_test``); this test is the
first half of that pair.

What differs from the SMC-SRAM sibling:

  * The ROM is built with ``BOOT_SPI_CONTROLLER_OT=1`` (``build_ot/``), so
    ``boot_flash.h`` links the OpenTitan driver (``ot_spi_flash_read_dma``) rather
    than the weak ``sep_spi.c`` stub that returns "SPI unavailable".
  * ``+sep_boot_from_spi`` makes the testbench seed ``STRAPS_LO[25]``
    (primary_chiplet) in the SMC responder, so ``boot_from_spi()`` is true and the
    ROM takes its SPI branch. Without it the ROM falls back to SMC-SRAM and this
    test would silently prove nothing -- hence the explicit path assertions below.
  * ``OcahSpiFlash`` answers on the SPI pads, preloaded with the packed image at
    flash offset 0. The packer lays the primary manifest at 0x1000, which is
    exactly ``PRIMARY_MANIFEST_OFFSET`` (manifest.h), so the ROM's fixed offsets
    line up with the image with no fixups.

The SMC responder is still present (target ``rom_boot``): the ROM reads its straps,
the DFX/mem-repair gate and the status ring from SMC regardless of boot source.
Only the manifest/payload transport changes.

Exercised datapath: flash BFM -> MISO -> OT spi_host RX FIFO -> (RX-watermark
lsio_trigger) -> Secure DMA -> SEP SRAM -> ROM SHA-256 validate -> BL1 jump.
"""

from __future__ import annotations

import os
from pathlib import Path

from sep_reg_meta import sym

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import SepEfuseImage, LC_TEST_DEV
from env.sep_rom_console import rom_console_task, log_scratch_cold
from ocah_spi_vip import OcahSpiFlash

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
_ROM_DIR = os.path.join(_SEP_ROOT, "bootrom", "prod")
# build_ot/ -- the OpenTitan-transport ROM with the DMA drain. Pointing this at
# build/ would load the stub ROM, which never touches SPI; the path assertions
# below would then fail. The PIO sibling overrides it with build_ot_pio/.
_FW_DIR = os.path.join(_ROM_DIR, "build_ot")
# Raw packed image for the flash BFM, from the DEFAULT build/ -- the packed
# manifest+BL1 bytes are transport- and drain-agnostic, so all three ROM variants
# (stub, OT+DMA, OT+PIO) read the same image and it is built once.
# NOT the .spi_preload variant: that is $readmemh text, while
# OcahSpiFlash.preload() reads raw binary.
_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build",
                            "non_secure_boot.bin")
# Signed sibling, same layout, RSA-3072 over the manifest (make secure_boot_spi).
SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build",
                                  "secure_boot.bin")

_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
# A serial flash read of the manifest (1184 B) plus the BL1 payload (5136 B) at
# the profile-0 SCK rate is far more sim time than the SMC-SRAM sibling's AXI
# fetch, so this budget is well above that test's 4M.
_MAX_RUN_CYCLES = 24_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 50_000

# Console markers that distinguish the two manifest sources. The ROM prints
# BOOT_SPI on the SPI branch (rom_main.c) and WAIT_SMC_MANIFEST on the SMC-SRAM
# branch, so requiring one and forbidding the other pins down which path ran.
_SPI_PATH_MARKER = "BOOT_SPI"
_SMC_PATH_MARKER = "WAIT_SMC_MANIFEST"
_MANIFEST_OK_MARKER = "MANIFEST_OK"


@pyuvm.test()
class sep_rom_ot_dma_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM with the manifest fetched over SPI."""

    build_env = False
    # Overridden by the signed sibling (sep_rom_ot_secure_boot_test), which reuses
    # this whole flow and only swaps the image and tightens the assertions.
    flash_image = _FLASH_IMAGE
    # ROM build directory, as class data so the PIO sibling can point at its own
    # variant without duplicating the scenario. It must agree with the
    # +sep_boot_rom_hex the testlist passes: this supplies the TCM images while
    # that supplies the ROM responder image, and a mismatched pair would run one
    # variant's .text against another's .rodata.
    rom_build_dir = _FW_DIR
    # Console lines that must appear / must not appear. The subclass appends the
    # RSA markers; keeping them as class data is what lets the two variants share
    # one scenario without a copy.
    required_markers = (_SPI_PATH_MARKER, _MANIFEST_OK_MARKER)
    forbidden_markers = (_SMC_PATH_MARKER,)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # BL1 (bl1_pass_test) prints on the SCRATCH2 virt console, not the mailbox
        # byte console the scoreboard's banner check reads -- same as the SMC-SRAM
        # sibling, so disable the banner check and gate on fw_done && fw_pass.
        self.sb.expected_line = ""
        # rom_lifecycle_policy validates the eFuse LC_STATE, so real fuse sense
        # runs (no +skip_fuse_sense). TEST_DEV is in the manifest's allowed
        # life_cycle_states (0x7).
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
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
        # Image at flash address 0: the packer's primary manifest lands at 0x1000
        # and the payload at 0x2000, matching the ROM's compiled-in offsets.
        flash.preload(self.flash_image)
        await flash.start()
        try:
            await self.boot_firmware(
                self.sb,
                os.path.join(self.rom_build_dir, "boot_rom.itcm.hex"),
                os.path.join(self.rom_build_dir, "boot_rom.dtcm.hex"),
                rst_vec=_ROM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            await flash.stop()
            log_scratch_cold(self.logger)

        # Positive evidence about WHICH path served this boot. The scoreboard's
        # fw_pass alone cannot tell the two manifest sources apart -- both end in
        # the same BL1 mailbox magic -- so without these the test would still pass
        # with the strap unset and prove nothing about SPI. The signed subclass
        # extends these tuples to also demand the RSA markers.
        for marker in self.required_markers:
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}. Console: {console}"
            )
        for marker in self.forbidden_markers:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which means it did not take the intended "
                f"path. Console: {console}"
            )
