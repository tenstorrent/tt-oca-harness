# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Secure-DMA vs CPU-LSU SRAM contention test (PyUVM).

OSS port of the reference suite ``sep_dma_cpu_contention_test``.
Boots the VeeR EL2 core and runs the dma_cpu_contention firmware: it starts a
long SRAM->SRAM Secure-DMA copy and, while it is in flight, runs a CPU store
loop into a disjoint SRAM region, so the DMA master and the CPU-LSU master
arbitrate at the shared SRAM slave on the SEP-local xbar. All internal to bare
``sep`` -- the firmware produces the contention, no testbench injection.

Firmware-self-checking: the firmware proves the streams overlapped (mid-flight
STATUS BUSY && !DONE), that the DMA reached DONE with no error, the STATUS RW1C
clear, and that BOTH the DMA-copied data and the CPU-written region are
bit-exact afterward (so neither master was starved/corrupted). main() returns
its error count and start.S emits the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF)
magic on the 0x8000_0000 mailbox, which the boot scoreboard gates on, alongside
the banner and ICCM-execution checks.

No fuse data is read, so the testlist entry uses ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_cpu_contention_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_cpu_contention_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# 2 KiB SRAM->SRAM copy + a 256 B CPU loop + two full-region verifies; the run
# loop early-exits on fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 4_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP DMA/CPU contention test"


@pyuvm.test()
class sep_dma_cpu_contention_test(sep_base_test):
    """Boot VeeR EL2 and run the Secure-DMA / CPU-LSU SRAM contention firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Override the boot scoreboard's expected banner here (after its own
        # build_phase, which resets it to the hello_world default).
        self.sb.expected_line = _BANNER
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
