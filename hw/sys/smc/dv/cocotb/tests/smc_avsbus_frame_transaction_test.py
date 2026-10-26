# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus command-to-response transaction set against a responding target."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_frame_transaction_test_seq import (
    smc_avsbus_frame_transaction_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_frame_transaction_test(smc_base_test):
    """Queue AVSBus commands, check their subframes and answer them with shaped replies."""

    required_evidence = (
        "CHK-AVS-CMD-FIFO-DRAIN",
        "CHK-AVS-FRAME-FSM-MAIN-PATH",
        "CHK-AVS-GRP0-SUBFRAME",
        "CHK-AVS-GRP1-SUBFRAME",
        "CHK-AVS-MASTER-SUBFRAME",
        "CHK-AVS-READBACK-FIFO-FILL",
        "CHK-AVS-READBACK-POP",
        "CHK-AVS-SLAVE-BAD-CRC",
        "CHK-AVS-SLAVE-INT-OBS",
        "CHK-AVS-SLAVE-STATUS-BIT1",
        "CHK-AVS-SUBFRAME-CRC-OBS",
        "CHK-AVS-VALID-ACK-NO-RETRY",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_frame_transaction_test_seq("smc_avsbus_frame_transaction_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: 3 AVS_CMD writes, 2 AVS_CFG_1 writes and
            # their readbacks, the entry and completion AVS_FIFOS_STATUS reads,
            # 3 AVS_READBACK pops with an occupancy read each, and the two
            # AVS_NORMAL_STATUS reads. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=18,
            csr_accesses=seq.accesses,
            proxy=False,
            details="AVSBus protocol frames driven from the SMC boundary with a responding pad",
        )
