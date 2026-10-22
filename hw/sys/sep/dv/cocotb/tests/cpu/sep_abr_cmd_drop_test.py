# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The ML-DSA verify driver refuses a verify whose command never reached Adams Bridge.

``+sep_abr_cmd_drop`` holds the accelerator's decoded ML-DSA command at NONE, so
every command write is dropped while ZEROIZE and every register write still land:
what an instruction-skip glitch on the command store produces. The
abr_mldsa87_verify_test firmware then runs only its genuine case. The accelerator
never preloads ``MLDSA_VERIFY_RES`` with the inverted c~, so the driver must stop at
its preload check with ``ABR_DRV_ERR_STATE``, having seen no command-done event,
and the firmware must report FAIL. A PASS line would mean the driver trusted a
verify that never ran.

The case runs from the same image as sep_abr_mldsa87_verify_test, with its case
mask patched to the genuine case alone.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_NAME = "abr_mldsa87_verify_test"
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", _FW_NAME)
_ITCM_HEX = os.path.join(_FW_DIR, f"{_FW_NAME}.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, f"{_FW_NAME}.dtcm.hex")

_CASE_PARAM_MAGIC = 0xAB2D5A87
_GENUINE_ONLY = 1 << 1

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 10_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 500_000

# The driver's status, stage and diagnostics when the preload never appears:
# ABR_DRV_ERR_STATE (-7) at ABR_DRV_STAGE_PRELOAD (5), nothing streamed, no done event.
_REFUSED_LINE = "case 1 genuine: FAIL status=-7 stage=5 written=0 early=0 inv=0 nz=0 done=0"
_ACCEPTED_LINE = "case 1 genuine: PASS"


@pyuvm.test()
class sep_abr_cmd_drop_test(sep_base_test):
    """A dropped ML-DSA command is refused at the preload check, never accepted."""

    build_env = False
    required_evidence = ("CHK-FW-CONSOLE",)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        # Without the plusarg the command lands, the genuine case passes, and the
        # run fails for a reason that says nothing about a dropped command.
        assert cocotb.plusargs.get("sep_abr_cmd_drop") is not None, (
            "+sep_abr_cmd_drop is not set: the command would land and this testcase "
            "would prove nothing about a command that never reached the accelerator"
        )
        dtcm_hex = os.path.join(os.getcwd(), f"{_FW_NAME}.genuine_only.dtcm.hex")
        patch_param_block(
            _DTCM_HEX, dtcm_hex, _CASE_PARAM_MAGIC, [_CASE_PARAM_MAGIC, _GENUINE_ONLY]
        )

        self.sb.expected_line = _REFUSED_LINE
        self.sb.expect_fw_pass = False
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            dtcm_hex,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        # boot_firmware grades only a PASS; this test expects a refusal, so it grades
        # the console itself.
        console = self.sb.console_text()
        assert _ACCEPTED_LINE not in console, (
            "CHK-FW-CONSOLE FAIL: the driver accepted a verify whose command was dropped"
        )
        assert _REFUSED_LINE in console, (
            f"CHK-FW-CONSOLE FAIL: firmware console missing {_REFUSED_LINE!r}"
        )
        self.logger.info(
            "CHK-FW-CONSOLE PASS: the dropped command was refused at the preload check"
        )
