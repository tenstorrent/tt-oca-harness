# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Real SEP DV dma firmware under the OSS SMU wrapper.

Boots hw/sys/sep/dv/fw/tests/sep_smu_dma, which exercises the SEP DMA engine register path on-chip and parks
in its own pass or fail loop. The verdict is the firmware's; the testbench only
watches which loop the SEP settles on.
"""

from __future__ import annotations

from seq_lib.sep_terminal_loop_seq import SepTerminalLoopSeq


class SmuSepDmaSeq(SepTerminalLoopSeq):
    NAME = "sep_dma"
    PASS_SYM = "smu_sep_dma_pass_loop"
    FAIL_SYMS = {"dma": "smu_sep_dma_fail_loop"}
    SYM_DEFAULT = "sep_smu_dma.tcm.sym"
    EVIDENCE = ("SEP_REAL_FW_DMA_OK", "SEP_DMA_CSR_PATH_OK")
