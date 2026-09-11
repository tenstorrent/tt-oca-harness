# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PIC source 40 claim + mask for the token-comparator redundancy fault.

cpu mode. Firmware arms PIC source 40 and presents a SEC_DISABLE token.
The host injects a collapse on that comparator after READY (tb port; no
LSU conflict). Firmware proves the ISR claim id, the SEC_DISABLE sticky
bit, and that masking meie[40] stops re-entry. TOKEN_MATCH_FAULT is sw=r;
there is no W1C.

+skip_fuse_sense: the SEC_DISABLE compare is not fuse-gated.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_SEC,
)

_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "token_match_fault_pic_test")
_ITCM_HEX = os.path.join(_FW_DIR, "token_match_fault_pic_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "token_match_fault_pic_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP token-match fault PIC test"
_READY = 0xE9050040
_READY_POLL = 200_000


@pyuvm.test()
class sep_efuse_token_match_fault_pic_test(sep_base_test):
    """Boot EL2; inject SEC_DISABLE collapse; firmware claims and masks PIC 40."""

    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _scratch0(self) -> int:
        return self.rd(cocotb.top.scratch_cold_probe_o) & 0xFFFF_FFFF

    async def _inject_after_ready(self) -> None:
        for _ in range(_READY_POLL):
            await ClockCycles(cocotb.top.clk_i, 1)
            if self._scratch0() == _READY:
                cocotb.top.token_cmp_fault_sel_i.value = TOKEN_CMP_SEL_SEC
                cocotb.top.token_cmp_fault_inject_i.value = TOKEN_CMP_INJECT_COLLAPSE
                self.logger.info("token-fault PIC: SEC_DISABLE collapse inject on")
                return
        raise AssertionError("firmware never published READY for the PIC inject")

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        cocotb.start_soon(self._inject_after_ready())
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        cocotb.top.token_cmp_fault_inject_i.value = TOKEN_CMP_INJECT_OFF
        console = self.sb.console_text()
        for needle in (
            "CHK-PIC-CLAIM PASS:",
            "CHK-PIC-FAULT PASS:",
            "CHK-PIC-MASK PASS:",
        ):
            if needle not in console:
                raise AssertionError(f"firmware missing {needle!r}")
        # The needles show the firmware reached each check; the magic is what
        # says it passed. Require both before logging a PASS summary.
        assert self.sb.fw_done and self.sb.fw_pass, (
            "firmware did not signal a PASS verdict; the console needles are not "
            "a verdict on their own"
        )
        self.logger.info("CHK-PIC-40 PASS: claim id 40, SEC_DISABLE sticky, mask stopped re-entry")
