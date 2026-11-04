# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CTRL_STATUS writes of any strobe start a clear, and STATUS reads 1 through the CSR in ST_ERROR.

Sources hw/ip/zeroer/regs/zeroer_ctrl.rdl (CTRL_STATUS, STATUS) and hw/sys/smc/doc/zeroer.adoc
(state machine table).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_strobe_error_status_test_seq import (
    smc_zeroer_strobe_error_status_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   6 output-fabric pass-all filter writes                                   6
#   DEST_ADDR, SIZE, CTRL_STATUS read, start, held read and after-read of    24
#   four starts
#   SIZE read, INT_EN write, DEST_ADDR and SIZE of the error leg, three      9
#   CTRL_STATUS reads, two readbacks
ZEROER_STROBE_ERROR_STATUS_MIN_CSR_ACCESSES = 39


@pyuvm.test()
class smc_zeroer_strobe_error_status_test(smc_base_test):
    """WSTRB 0x00, 0x0F and 0xF0 starts clear the region; STATUS reads 1 in ST_ERROR, 0 after reset."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZEROER-ERROR-STATUS-CSR",
        "CHK-ZEROER-ZERO-STROBE-START",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_strobe_error_status_test_seq("smc_zeroer_strobe_error_status_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_STROBE_ERROR_STATUS_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="zeroer strobed starts and ST_ERROR CSR status graded",
        )
