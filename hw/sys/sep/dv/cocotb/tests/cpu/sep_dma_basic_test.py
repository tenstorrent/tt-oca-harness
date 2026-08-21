# SPDX-License-Identifier: Apache-2.0
"""SEP Secure-DMA basic-breadth firmware-boot test (PyUVM).

OSS rep DMA basic breadth. reference provenance: the uvm_tests/dma reg_rw / reg_reset /
cfg_regwen / range_regwen / addr_fixed / addr_wrap / addr_combo / mem_copy
(width sweep) / err_opcode family. Boots the VeeR EL2 core and runs the
dma_basic firmware, which drives the Secure DMA over the CPU LSU and proves the
DMA CSR + copy-datapath basic contracts on bare sep (SRAM->SRAM transfers).

Distinct from the Phase-1 DMA trio (sep_dma_hash inline SHA-256 + SRAM->DCCM +
IRQ; sep_dma_cpu_contention mid-flight BUSY + dual-master; sep_spi_ot_dma_rx
lsio handshake): DMA basic breadth adds the CSR/REGWEN breadth, the FIXED/INCR/WRAP address-
mode matrix, the 1B/2B/4B transfer-width sweep, and one opcode-error path.

Firmware-self-checking: the firmware returns its error count and start.S emits
the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on the 0x8000_0000 mailbox, which
the boot scoreboard gates on. The firmware self-checks (each with a positive PASS
line in the console log): CHK-RESET (reset values), CHK-CFG-REGWEN (HW busy-lock),
CHK-RANGE-REGWEN (range gating + rw0c lock), CHK-COPY-MODE (FIXED/INCR/WRAP
expected images + neighbor), CHK-WIDTH (1B/2B/4B), CHK-DONE-RW1C, CHK-ERR-OPCODE
(opcode_error + recovery). The scoreboard also checks the banner + ICCM execution.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm

from sep_base_test import sep_base_test
from env.sep_boot_scoreboard import SepBootScoreboard

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_basic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_basic_test.dtcm.hex")

_ICCM_BASE = 0xC000_0000
# A handful of tiny SRAM->SRAM copies + one 1 KiB busy-lock copy; the run loop
# early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA basic test"


@pyuvm.test()
class sep_dma_basic_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA basic-breadth firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb, _ITCM_HEX, _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
