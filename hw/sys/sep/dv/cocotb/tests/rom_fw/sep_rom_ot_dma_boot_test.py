# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
The PIO variant is ``sep_rom_ot_pio_boot_test`` (built by
``ot-pio-toolchain-images``); this test is the DMA half of the pair.

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
    exactly ``PRIMARY_MANIFEST_OFFSET``, so the ROM's fixed offsets
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

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_esrc_noise import esrc_noise_task
from env.sep_rom_console import log_scratch_cold, rom_console_task
from ocah_spi_vip import OcahSpiFlash
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_SEP_ROOT = str(Path(__file__).resolve().parents[4])
# Raw packed image for the flash BFM, from the DEFAULT build/ -- the packed
# manifest+BL1 bytes are transport- and drain-agnostic, so all three ROM variants
# (stub, OT+DMA, OT+PIO) read the same image and it is built once.
# NOT the .spi_preload variant: that is $readmemh text, while
# OcahSpiFlash.preload() reads raw binary.
# OCA boot manifests, built by `make oca-images`.
_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_non_secure_boot.bin")
# Signed sibling, same layout, RSA-3072 over the manifest's signed region.
SECURE_FLASH_IMAGE = os.path.join(_SEP_ROOT, "bootrom", "prod", "build", "oca_secure_boot.bin")

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
# Printed after the payload hash chain and TOC entry hashes verified -- i.e. the
# bytes about to be jumped to are the ones the manifest describes, not merely
# bytes that arrived. Distinct from MANIFEST_OK, which says only that the
# manifest itself was sound.
_PAYLOAD_OK_MARKER = "PAYLOAD_OK"
# Flash-relative manifest offset. This is the transport evidence that is NOT entailed
# by BOOT_SPI: the SMC-SRAM branch prints an absolute 0x4006xxxx address, so only the
# OT-SPI branch can print 0x00001000. See the note on forbidden_markers below.
_MANIFEST_SRC_MARKER = "MANIFEST_SRC=0x00001000"


@pyuvm.test()
class sep_rom_ot_dma_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM with the manifest fetched over SPI."""

    build_env = False

    # Gate on the ROM/BL1 verdict word in cold_scratch[0] rather than the
    # outbound mailbox. Inherited by every subclass in this directory.
    verdict_source = "scratch0"
    # Overridden by the signed sibling (sep_rom_ot_secure_boot_test), which reuses
    # this whole flow and only swaps the image and tightens the assertions.
    flash_image = _FLASH_IMAGE
    # Console lines that must appear / must not appear. The subclass appends the
    # RSA markers; keeping them as class data is what lets the two variants share
    # one scenario without a copy.
    # Cycle budget for poll_boot. Class data so a test whose boot ends earlier --
    # a negative test that is refused before the payload is ever fetched -- can
    # trim it. poll_boot breaks out on fw_done, so this is normally a backstop;
    # it only becomes the runtime if the firmware neither passes nor reports.
    max_run_cycles = _MAX_RUN_CYCLES
    required_markers = (
        _SPI_PATH_MARKER,
        _MANIFEST_SRC_MARKER,
        _MANIFEST_OK_MARKER,
        _PAYLOAD_OK_MARKER,
    )
    # Kept as a cheap guard, but it is NOT independent evidence: BOOT_SPI and
    # WAIT_SMC_MANIFEST sit on complementary arms of the same predicate
    # (boot_from_spi(straps)) within one boot, and there is no fallback edge -- if every
    # SPI manifest slot fails the ROM errors out rather than retrying via SMC. So given
    # the required BOOT_SPI marker passed, this forbid cannot fail. The non-entailed
    # transport evidence is _MANIFEST_SRC_MARKER above.
    forbidden_markers = (_SMC_PATH_MARKER,)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def build_efuse_image(self):
        """OTP image for this run. Override to boot under a different lifecycle.

        Default: a zero image stamped TEST_DEV. Subclasses that need a specific
        lifecycle (e.g. PROD, to make secure boot enforced rather than
        manifest-selected) return ``self.select_efuse_image()`` instead, so the
        image comes from the ``+sep_efuse_preload`` the testlist names -- which is
        the only route that also gets it into the DUT at t=0, via the prestage
        hook. Building one here alone would be too late to change LC_STATE.
        """
        image = SepEfuseImage()
        image.set_lc_state(LC_TEST_DEV)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        """Hook for negative testcases: mutate the packed image before load.

        Default is identity, so the positive boot tests are unaffected. Returning
        the buffer (rather than mutating in place only) keeps a wholesale
        replacement possible.
        """
        return buf

    def log_transport(self, flash) -> None:
        """Hook to dump the flash BFM's transaction history. Default is a no-op.

        Called from the ``finally`` below, so it runs BEFORE any marker assertion
        can abort the test: the SPI address sequence is the most useful artifact
        for diagnosing a failure in these testcases, and logging it from
        :meth:`check_transport`, which runs after the marker loop, would let a
        missing console marker suppress the evidence needed to explain it. Logging
        only, never asserting: a raise here would mask the real exception.
        """

    def check_transport(self, console: list[str], flash) -> None:
        """Hook for the SPI address-detect testcases.

        Runs after the marker checks below, with the console lines and the flash
        BFM still holding its transaction history. It exists because the
        ``required_markers`` mechanism can only ask "does this string appear
        anywhere", which cannot express either of the two things an
        address-detection testcase must establish: the ORDER of the slot reads,
        and what the DEVICE actually returned at each address. Default is a no-op.
        """

    async def run_scenario(self) -> None:
        dut = cocotb.top
        # BL1 (bl1_pass_test) prints on the SCRATCH2 virt console, not the mailbox
        # byte console the scoreboard's banner check reads -- same as the SMC-SRAM
        # sibling, so disable the banner check and gate on fw_done && fw_pass.
        self.sb.expected_line = ""
        # rom_lifecycle_policy validates the eFuse LC_STATE, so real fuse sense
        # runs (no +skip_fuse_sense). TEST_DEV is in the manifest's allowed
        # life_cycle_states (0x7).
        # Raw noise for the entropy source. The ROM brings the ESRC -> CSRNG ->
        # EDN chain up itself before driving OTBN or AES, and +esrc_noise_force
        # only FORCES the decorrelator inputs from this port -- it generates
        # nothing. Without a driver the port sits at 0, the repetition health test
        # trips, and the ROM correctly refuses to boot on a dead entropy source.
        #
        # Started for every SPI ROM test, not just the crypto ones: it is cheap,
        # and a test that later grows a crypto dependency should not have to
        # rediscover this.
        cocotb.start_soon(esrc_noise_task(dut, logger=self.logger))

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
        # Image at flash address 0: the packer's primary manifest lands at 0x1000
        # and the payload at 0x2000, matching the ROM's compiled-in offsets.
        # Loaded as bytes so mutate_flash_image() can inject a defect; preload()
        # accepts a buffer as readily as a path, so a negative testcase needs no
        # build step and no new firmware profile.
        with open(self.flash_image, "rb") as fh:
            image = bytearray(fh.read())
        loaded = bytes(self.mutate_flash_image(image))
        # Length of what was actually preloaded, for check_transport(): the backup
        # slot's span runs to the end of the image, so the slot-address checks need
        # the post-mutation size rather than the on-disk one.
        self._image_len = len(loaded)
        flash.preload(loaded)
        await flash.start()
        try:
            # No TCM staging: the ROM runs from Boot ROM (+sep_boot_rom_hex) and
            # pulls BL1 off SPI into ICCM itself, so there is no firmware image for
            # the tcm_load_i backdoor to place. Valid ECC comes from the vector.S
            # scrub for DCCM and from the DMA that loads BL1 for ICCM, within the
            # loaded image only.
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            await self.poll_boot(
                self.sb,
                max_run_cycles=self.max_run_cycles,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            await flash.stop()
            self.log_transport(flash)
            log_scratch_cold(self.logger)

        # Positive evidence about WHICH path served this boot. The scoreboard's
        # fw_pass alone cannot tell the two manifest sources apart -- both end in
        # the same BL1 mailbox magic -- so without these the test would still pass
        # with the strap unset and prove nothing about SPI. The signed subclass
        # extends these tuples to also demand the RSA markers.
        # Guard the guards. An empty marker tuple or a dark console would otherwise
        # make every check below vacuously true, and without the per-marker log line
        # a 0-marker run would be indistinguishable from a 5-marker one.
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
            self.logger.info("CHK-ROM-PATH PASS: required marker observed: %s", marker)
        for marker in self.forbidden_markers:
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which means it did not take the intended "
                f"path. Console: {console}"
            )

        # Device-side evidence, for the testcases that need it. No-op by default.
        self.check_transport(console, flash)
