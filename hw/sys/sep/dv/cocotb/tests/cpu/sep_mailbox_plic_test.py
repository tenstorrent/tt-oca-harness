# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP outbound-mailbox -> PIC -> CPU interrupt-delivery test (PyUVM).

OSS port of the reference suite ``sep_mailbox_plic_test``. Boots the VeeR EL2 core and runs
the mailbox_plic firmware, which arms outbound mailbox 0 (axil_mailbox @
0x10A0_0000), self-triggers its threshold interrupt by pushing a word into the
FIFO, and proves the interrupt reaches the CPU through the VeeR PIC (WFI + ISR):
``axil_mailbox.outbound_interrupt_o[0]`` -> ``sep_internal_interrupts[0]`` ->
PIC source 1 -> CPU trap -> ISR. The whole path is internal to bare ``sep`` -- no
testbench injection.

Like the other FW-boot tests this is firmware-self-checking: the firmware
returns its error count and start.S emits the PASS (0xCAFEBABE) / FAIL
(0xDEADBEEF) magic on the 0x8000_0000 mailbox, which the boot scoreboard gates
on. The firmware self-checks the exact PIC claim id (== 1), the asserted IRQP/
IRQS write bit, the IRQS/IRQP W1C-clear readback, and the absence of an
interrupt storm; a failed check makes start.S emit FAIL. The scoreboard also
checks the firmware banner and that the core executed out of ICCM.

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
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "mailbox_plic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "mailbox_plic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Arm + trigger + ISR + a 256-iteration quiet window; the run loop early-exits on
# fw_done, so this is an upper bound.
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP mailbox PLIC test"


@pyuvm.test()
class sep_mailbox_plic_test(sep_base_test):
    """Boot VeeR EL2 and run the outbound-mailbox PIC-delivery firmware."""

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
