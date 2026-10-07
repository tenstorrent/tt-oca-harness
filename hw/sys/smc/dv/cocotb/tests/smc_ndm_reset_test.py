# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDM request pin to REQUEST/IRQ to PROCESS CSR to process_o."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ndm_reset_test_seq import smc_ndm_reset_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ndm_reset_test(smc_base_test):
    """Per-cluster NDM handshake without Force or firmware."""

    required_evidence = (
        "CHK-NDM-CLR-0",
        "CHK-NDM-CLR-1",
        "CHK-NDM-CLR-2",
        "CHK-NDM-CLR-3",
        "CHK-NDM-COUNT",
        "CHK-NDM-DROP-0",
        "CHK-NDM-DROP-1",
        "CHK-NDM-DROP-2",
        "CHK-NDM-DROP-3",
        "CHK-NDM-IDLE",
        "CHK-NDM-PROC-0",
        "CHK-NDM-PROC-1",
        "CHK-NDM-PROC-2",
        "CHK-NDM-PROC-3",
        "CHK-NDM-REQ-0",
        "CHK-NDM-REQ-1",
        "CHK-NDM-REQ-2",
        "CHK-NDM-REQ-3",
    )
    min_evidence = 18

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ndm_reset_test_seq("ndm_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The NDMRESET_REQUEST / NDMRESET_PROCESS readback expectations, the
        # bounded `_await_pins` handshakes and the PROCESS write-to-`process_o`
        # path are asserted inside the sequence and scoreboard-enforced; this
        # guard only catches a sequence body that never ran.
        assert seq.bits_swept, (
            f"the per-cluster handshake swept no bits "
            f"(cluster_count={seq.cluster_count}); no per-bit REQUEST/PROCESS "
            f"stimulus was issued in this run"
        )
