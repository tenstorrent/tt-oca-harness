# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV wdt firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_wdt, which exercises the SEP watchdog timer control and threshold register path on-chip and parks
in its own pass or fail loop. The verdict is the firmware's; the testbench only
watches which loop the SEP settles on.
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepWdtSeq(SepTerminalLoopSeq):
    NAME = "sep_wdt"
    PASS_SYM = "smu_sep_wdt_pass_loop"
    FAIL_SYMS = {"wdt": "smu_sep_wdt_fail_loop"}
    SYM_DEFAULT = "sep_smu_wdt.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_WDT_OK", "SEP_WDT_CSR_PATH_OK")
