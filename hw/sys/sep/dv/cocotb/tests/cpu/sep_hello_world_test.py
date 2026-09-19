# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP firmware-boot test (PyUVM): boot the VeeR EL2 core from ICCM and run the
prebuilt hello_world firmware.

Brings up clocks, backdoor-loads the TCM responder with the hello_world image,
passes the desired reset vector to tb_top.sv, which programs the EL2 reset-vector
TDR through JTAG, and asserts mpc_reset_run_req so the core boots and runs firmware
out of the TCM. The scoreboard checks:
  * the EL2 retired-instruction trace advances (the core actually executes);
  * the firmware console emits "Hello from SEP OSS firmware!" on the outbound
    mailbox; and
  * the firmware signals PASS (0xA5A55A5A -> 0xCAFEBABE at 0x80000000).

The firmware image is fw/build/tests/hello_world/*.{itcm,dtcm}.hex, built by the
c_compile stage (make dv-fw-tests TEST=hello_world).
This test stages those byte images into the sim cwd as sep_itcm.hex/sep_dtcm.hex
and pulses tcm_load_i so the SV responder $readmemh-backdoors them before the
core leaves reset (keeps absolute firmware paths out of the build config).
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

# Firmware lives under the DV tree (sibling of cocotb/); parents[3] of
# .../cocotb/tests/cpu/<file> is the DV root.
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "hello_world")
_ITCM_HEX = os.path.join(_FW_DIR, "hello_world.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "hello_world.dtcm.hex")

# Reset PC -> ICCM base; rst_vec carries PC[31:1] to tb_top.sv.
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
# Boot bound: hello_world (filter init + picolibc printf + test_pass) completes
# well within this; the run loop early-exits on fw_done.
_MAX_RUN_CYCLES = 2_000_000
# If the core has not retired a single instruction by here, it never booted.
_NO_BOOT_CYCLES = 80_000
# Emit a progress line every this many cycles (visibility into a slow/stuck boot).
_PROGRESS_EVERY = 2_000


@pyuvm.test()
class sep_hello_world_test(sep_base_test):
    """Boot VeeR EL2 from ICCM and run the hello_world firmware."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )

        # CHK-BOOT: the console line is the evidence the card names -- only executed
        # code out of tightly-coupled memory can produce it. The boot scoreboard
        # raises on its absence; assert it here too so the record rests on the text
        # rather than on the run having ended.
        console = self.sb.console_text()
        assert self.sb.expected_line in console, (
            f"firmware console has no {self.sb.expected_line!r}, so the core did not "
            f"reach the firmware entry point. Console was:\n{console}"
        )
        self.logger.info(
            "CHK-BOOT PASS: %r on the console, so the core executed from "
            "tightly-coupled memory and reached the entry point",
            self.sb.expected_line,
        )
