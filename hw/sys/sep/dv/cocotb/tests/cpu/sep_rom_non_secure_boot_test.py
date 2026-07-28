# SPDX-License-Identifier: Apache-2.0
"""SEP ROM non-secure boot test (PyUVM) -- real Boot ROM, SPI stubbed.

Boots the VeeR EL2 core from the REAL production Boot ROM (fw/sep/bootcode,
copied+trimmed into dv/.../fw/bootcode) at ROM_BASE. SPI is stubbed
(src/sep_spi.c) because the OSS `sep` DUT has no Cadence xSPI, so the ROM takes
its non-SPI (SMC-SRAM) manifest path. The manifest + BL1 payload are provided by
a behavioral SMC responder in the testbench; BL1 signals PASS on the mailbox.

Boot images (built by fw/bootcode/Makefile):
  boot_rom.vmem      -> Boot ROM responder (+sep_boot_rom_hex), 64-bit words
  boot_rom.dtcm.hex  -> DCCM (.rodata/.data/.bss), backdoor-loaded to the TCM
                        responder (ROM .text executes from the ROM responder).

The CPU reset vector points at ROM_BASE (0x10040000), so the core fetches and
runs the real ROM -- not a backdoored payload.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge
import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_efuse_image import SepEfuseImage, LC_TEST_DEV

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "bootcode", "build")
_ITCM_HEX = os.path.join(_FW_DIR, "boot_rom.itcm.hex")  # ROM .text (ICCM copy; harmless)
_DTCM_HEX = os.path.join(_FW_DIR, "boot_rom.dtcm.hex")  # ROM .rodata/.data/.bss -> DCCM

# Reset PC -> Boot ROM base 0x10040000 (SEP_BOOT_ROM_MEM_BASE_ADDR). rst_vec = PC[31:1].
_ROM_BASE = 0x1004_0000
# The ROM runs a long init + manifest/DMA/handoff sequence; give it room.
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 200_000
_PROGRESS_EVERY = 5_000


@pyuvm.test()
class sep_rom_non_secure_boot_test(sep_base_test):
    """Boot VeeR EL2 from the real Boot ROM and hand off to BL1 (SPI stubbed)."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def _scratch2_console(self) -> None:
        """Decode the ROM virt-console (SEP cold_scratch[2] = probe word 2).
        Protocol: [31:24]=c3 [23:16]=c2 [15:8]=c1 [3:1]=op(0=ASCII) [0]=toggle.
        The ROM re-writes with a flipped toggle for repeated values."""
        dut = cocotb.top
        line = bytearray()
        prev = None
        try:
          while True:
            await RisingEdge(dut.clk_i)
            try:
                v = int(dut.scratch_cold_probe_o.value)
            except Exception:  # noqa: BLE001
                continue
            w = (v >> 64) & 0xFFFFFFFF          # cold_scratch[2]
            if w == prev:
                continue
            prev = w
            for sh in (8, 16, 24):             # c1, c2, c3
                c = (w >> sh) & 0xFF
                if c == 0:
                    continue
                if c == 0x0A:
                    self.logger.info("ROM> %s", bytes(line).decode("ascii", "ignore"))
                    line = bytearray()
                elif 0x20 <= c <= 0x7E:        # printable ASCII only
                    line.append(c)
        except Exception:  # noqa: BLE001
            return  # end-of-sim tears down the clock; stop decoding cleanly

    async def run_scenario(self) -> None:
        # This BL1 (bl1_pass_test) prints "BL1"/"OBF"/"GO!" on the SCRATCH2 virt
        # console (decoded by _scratch2_console below), NOT the mailbox byte
        # console the scoreboard's banner check reads -- so disable that banner
        # check. PASS is gated on the real criteria: fw_done && fw_pass (the BL1
        # 0xA5A55A5A->0xCAFEBABE mailbox magic) plus EL2 PC-advance. The ROM+BL1
        # boot markers (BL1/OBF/FUSE_OK/GO!) are visible in the scratch2 console log.
        self.sb.expected_line = ""
        # The ROM's rom_lifecycle_policy validates the eFuse LC_STATE, so real
        # fuse-sense runs (no +skip_fuse_sense) with a golden image present.
        # TEST_DEV (raw 0x0) is in the manifest's allowed life_cycle_states (0x7).
        efuse_img = SepEfuseImage()
        efuse_img.set_lc_state(LC_TEST_DEV)
        self.write_efuse_image(efuse_img)
        cocotb.start_soon(self._scratch2_console())
        try:
            await self.boot_firmware(
                self.sb, _ITCM_HEX, _DTCM_HEX,
                rst_vec=_ROM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
            )
        finally:
            # cold_scratch[1] carries the ROM error code (STATUS_ENCODE: low 16b
            # = ROM_ERR_*). Dump the scratch tap so an early ROM FAIL is diagnosable.
            try:
                v = int(cocotb.top.scratch_cold_probe_o.value)
                for i in range(4):
                    self.logger.info("scratch_cold[%d] = 0x%08x", i,
                                     (v >> (32 * i)) & 0xFFFFFFFF)
            except Exception as exc:  # noqa: BLE001
                self.logger.info("scratch_cold dump failed: %s", exc)
