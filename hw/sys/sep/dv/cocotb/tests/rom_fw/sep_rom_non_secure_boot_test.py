# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ROM non-secure boot test (PyUVM) -- real Boot ROM, SPI stubbed.

Boots the VeeR EL2 core from the REAL production Boot ROM
(`hw/sys/sep/bootrom/prod`) at ROM_BASE. SPI is stubbed
(`hw/sys/sep/bootrom/prod/src/sep_spi.c`) because the OSS `sep` DUT has no
pad-muxed SPI host, so the ROM takes
its non-SPI (SMC-SRAM) manifest path. The manifest + BL1 payload are provided by
a behavioral SMC responder in the testbench; BL1 signals PASS on the mailbox.

Boot images (built by hw/sys/sep/bootrom/prod/Makefile):
  boot_rom.vmem      -> Boot ROM responder (+sep_boot_rom_hex), 64-bit words
  boot_rom.dtcm.hex  -> DCCM (.rodata/.data/.bss), backdoor-loaded to the TCM
                        responder (ROM .text executes from the ROM responder).

The CPU reset vector points at ROM_BASE (0x10040000), so the core fetches and
runs the real ROM -- not a backdoored payload.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_console import log_scratch_cold, rom_console_task
from sep_base_test import sep_base_test
from sep_reg_meta import sym

# Reset PC -> Boot ROM base 0x10040000 (SEP_BOOT_ROM_MEM_BASE_ADDR). rst_vec = PC[31:1].
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
# The ROM runs a long init + manifest/DMA/handoff sequence; give it room.
_MAX_RUN_CYCLES = 4_000_000

# Markers that must appear on the ROM's scratch virtual console.
#
#   SMC_MEM_CHK        boot-ROM stage: the SMC memory check ran
#   MANIFEST_HASH_OK   the ROM reports it validated the manifest hash
#   PLD_HASH_OK        the ROM reports it validated the payload hash
#   BL1, FUSE_CHK      emitted by the copied payload AFTER handoff
#
# The pair at the end is what evidences the transfer of control: those two strings
# exist only in the BL1 source, nowhere in the boot-ROM sources. The two hash
# markers are the closest this test comes to evidencing integrity checking -- note
# they show the ROM *reports* the check, not that a corrupted manifest would be
# rejected. Nothing here corrupts one, so the negative direction is untested.
_REQUIRED_ROM_MARKERS = (
    "SMC_MEM_CHK",
    "MANIFEST_HASH_OK",
    "PLD_HASH_OK",
    "BL1",
    "FUSE_CHK",
)
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 5_000


@pyuvm.test()
class sep_rom_non_secure_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM and hand off to BL1 (SPI stubbed)."""

    build_env = False

    # Gate on the ROM/BL1 verdict word in cold_scratch[0] rather than the
    # outbound mailbox. Inherited by every subclass in this directory.
    verdict_source = "scratch0"

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # This BL1 (bl1_pass_test) prints "BL1"/"OBF"/"GO!" on the SCRATCH2 virt
        # console (decoded by _scratch2_console below), NOT the mailbox byte
        # console the scoreboard's banner check reads -- so disable that banner
        # check. PASS is gated on the real criteria: fw_done && fw_pass (the BL1
        # 0xA5A55A5A->0xCAFEBABE mailbox magic) plus EL2 PC-advance. The ROM+BL1
        # boot markers (BL1/OBF/FUSE_OK/GO!) are visible in the scratch2 console log.
        self.sb.expected_line = ""
        self._rom_markers: list[str] = []
        # The ROM's rom_lifecycle_policy validates the eFuse LC_STATE, so real
        # fuse-sense runs (no +skip_fuse_sense) with a golden image present.
        # TEST_DEV (raw 0x0) is in the manifest's allowed life_cycle_states (0x7).
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)
        cocotb.start_soon(rom_console_task(self.logger, sink=self._rom_markers))
        try:
            # No TCM staging: the ROM runs from Boot ROM (+sep_boot_rom_hex) and
            # pulls BL1 off SPI into ICCM itself, so there is no firmware image for
            # the tcm_load_i backdoor to place. Valid ECC comes from the vector.S
            # scrub for DCCM and from the DMA that loads BL1 for ICCM, within the
            # loaded image only.
            await self.bring_up_cpu_boot(_ROM_BASE >> 1, run_pulse_cycles=40)
            await self.poll_boot(
                self.sb,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
            # The stage markers are the only evidence that the ROM took the
            # non-secure path at all, so require them rather than merely printing
            # them. Without this the whole virtual console could go dark -- a
            # dropped -DDEBUG, a broken cold_scratch write, a dead probe tap --
            # and the run would still be green, because the PASS gate is fed from
            # the outbound mailbox, a different target entirely.
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
