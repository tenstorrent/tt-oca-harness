# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A WDT bark fires the NMI into the handler at SEP_NMI_VEC, and SEP_NMI_VEC locks sticky.

OCAH provenance: ``sep_nmi_sanity_test`` checks the NMI vector, lock and
watchdog-bark delivery.

The nmi_sanity firmware checks the NMI mechanism on bare ``sep``: trampoline alignment,
SEP_NMI_VEC reset default / writeback / sticky lock, and that a WDT bark fires the NMI into the
registered handler (hw/sys/sep/rtl/sep.sv connects ``nmi_int_i`` to ``intr_wdog_timer_bark``
and ``nmi_vec_i`` to the SEP_NMI_VEC output), with no testbench injection.
fw/startup/crt0.s emits PASS/FAIL magic from the error count, which the boot
scoreboard gates on; a wedged NMI path reports FAIL or stalls into the scoreboard timeout.

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
    """The NMI vector CSR and the WDT bark -> NMI path pass their firmware checks."""

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
