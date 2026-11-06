# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer command capture at the trigger, 256-beat bursts, SIZE storage and a constant BREADY.

Sources hw/sys/smc/doc/zeroer.adoc (state machine, AXI4 master characteristics, outstanding
transaction management) and hw/ip/zeroer/regs/zeroer_ctrl.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_capture_burst_test_seq import smc_zeroer_capture_burst_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   6 output-fabric pass-all filter writes                                   6
#   66 SIZE pattern writes and readbacks, the restore and its readback     134
#   DEST_ADDR, SIZE and start writes of two jobs, the mid-job rewrite        8
#   DEST_ADDR and SIZE readbacks during and after the captured job           4
ZEROER_CAPTURE_BURST_MIN_CSR_ACCESSES = 152


@pyuvm.test()
class smc_zeroer_capture_burst_test(smc_base_test):
    """SIZE storage, DEST_ADDR/SIZE capture at the trigger, AWLEN 255 bursts, BREADY constant 1."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZEROER-AWLEN-255",
        "CHK-ZEROER-BREADY-CONSTANT",
        "CHK-ZEROER-CAPTURE-AT-START",
        "CHK-ZEROER-SIZE-PATTERN",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_capture_burst_test_seq("smc_zeroer_capture_burst_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_CAPTURE_BURST_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details="zeroer capture, burst length, SIZE storage and BREADY scenarios completed",
        )
