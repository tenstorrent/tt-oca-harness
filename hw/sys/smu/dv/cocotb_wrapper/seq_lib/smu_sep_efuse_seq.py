# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV efuse firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_efuse, which exercises the SEP-side eFuse control and external-shim CSR read/write path on-chip and parks
in its own pass or fail loop. The verdict is the firmware's; the testbench only
watches which loop the SEP settles on.
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepEfuseSeq(SepTerminalLoopSeq):
    NAME = "sep_efuse"
    PASS_SYM = "smu_sep_efuse_pass_loop"
    FAIL_SYMS = {"efuse": "smu_sep_efuse_fail_loop"}
    SYM_DEFAULT = "sep_smu_efuse.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_EFUSE_OK", "SEP_EFUSE_CSR_PATH_OK")
