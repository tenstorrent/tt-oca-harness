# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R4_001 ANCHOR: smc_log_engine_transfer_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 047d42022e2d641a47ec590f36f30504d88952df77710af282fbfb6d5b7d11fd
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R4_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Log-engine registers and all-16-slot transfers on all four uart_log_engine_wrap instances.

Reads the log-engine bank and the wrapper control register of every wrapper at reset,
writes and reads back the writable log-engine registers other than LOG_CTRL with
CTRL.EN = 0, sends two characters through each UART in MCR.LOOP, then gives all 16 LOG_CTRL
elements of every wrapper a non-zero length of at most one fetch word over its own 0x80-byte
SPM region and receives the 72 bytes back through RBR. Every element must read 0 afterwards, a length held with CTRL.EN = 0 must stay pending
and send nothing until the engine is enabled, wrapper 0's fetches from SYS_OUT memory must
each be one 8-byte AR, and INTR_STATUS must read clear after the transfers and follow
INTR_TEST and RW1C.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_log_engine_transfer_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_log_engine_transfer_test_seq import smc_log_engine_transfer_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every poll adds to it.
#
#   setup read                                                                1
#   S2: 4 x (23 reset words, INTR_TEST, wrapper CTRL, 10 UART registers)    140
#   S3: 4 x (CTRL.EN read, 5 registers x 3 values written and read, UART_EN
#       written and read twice)                                             140
#   S4: 4 x (UART arm 10, two characters x THR, LSR, RBR, LSR)               72
#   S5: 4 x (16 slot words written and read, 8 engine setup accesses, 16
#       triggers, one LSR and one RBR read per byte of 72)                  800
#   S6: 4 x (16 clear polls, LSR, INTR_STATUS)                               72
#   S7: 4 x (EN off, 16 triggers, 256 hold reads, 16 held reads, EN on,
#       first-character poll and RBR, 15 bytes x 2, 16 clear polls)        1352
#   S8: EN off, 3 filter saves, 3 filter writes, region 3, EN on, 4 triggers,
#       34 bytes x 2, 4 clear polls, EN off, 3 filter restores               91
#   S9: 4 x (INTR_ENABLE read, 2 bits x 3 writes and reads)                  52
#   S10: 4 x (EN off and read, 4 registers cleared and read, UART restore 8,
#        UART_EN read)                                                       76
LOG_ENGINE_TRANSFER_MIN_CSR_ACCESSES = 2796


@pyuvm.test()
class smc_log_engine_transfer_test(smc_base_test):
    """Run the log-engine register, transfer, enable and outbound-fetch legs on every wrapper."""

    required_evidence = (
        "CHK-LE-ENABLE-GATE",
        "CHK-LE-FETCH-OUTBOUND",
        "CHK-LE-FIFO-DRAIN",
        "CHK-LE-LEN-PENDING",
        "CHK-LE-REG-RESET",
        "CHK-LE-REG-RW",
        "CHK-LE-UART-LOOP",
        "CHK-LOG-ENGINE-TRANSFER-BYTES",
        "CHK-LOG-ENGINE-TRANSFER-CLEAN",
        "CHK-LOG-ENGINE-TRANSFER-HWCLR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_transfer_test_seq("smc_log_engine_transfer_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=LOG_ENGINE_TRANSFER_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.transfers} wrapper transfers, {seq.bytes_checked} log bytes compared, "
                f"{seq.hwclr_elements} LOG_CTRL elements cleared by hardware"
            ),
        )
