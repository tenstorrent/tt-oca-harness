# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP NMI sanity test (PyUVM).

OSS port of the reference suite ``sep_nmi_sanity_test``. Boots the VeeR EL2 core and runs
the nmi_sanity firmware, which verifies the NMI mechanism on bare ``sep``:
the NMI trampoline alignment, SEP_NMI_VEC reset default / writeback / sticky
lock, and that a WDT bark actually fires the NMI and reaches the registered
handler. The whole path is internal to bare ``sep`` (sep.sv:
``nmi_int = intr_wdog_timer_bark``, ``nmi_vec`` driven by the SEP_NMI_VEC CSR) --
no testbench injection.

Firmware-self-checking like the other FW-boot tests: the firmware returns its
error count and start.S emits the PASS (0xCAFEBABE) / FAIL (0xDEADBEEF) magic on
the 0x8000_0000 mailbox, which the boot scoreboard gates on. A wedged NMI path
either makes the firmware report FAIL or stalls the boot (the scoreboard times
out) -- it cannot pass vacuously.

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
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "nmi_sanity_test")
_ITCM_HEX = os.path.join(_FW_DIR, "nmi_sanity_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "nmi_sanity_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Boot + register checks + a few WDT bark ticks (~20 us sim); the run loop
# early-exits on fw_done so this is an upper bound.
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP NMI sanity test"


@pyuvm.test()
class sep_nmi_sanity_test(sep_base_test):
    """Boot VeeR EL2 and run the NMI sanity firmware (WDT bark -> NMI)."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
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
