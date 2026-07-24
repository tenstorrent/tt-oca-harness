# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM sideband AVSBus+OCTS fake-BFM test (P2 Phase A #3)."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_sideband_avsbus_octs_bfm_test_seq import (
    smc_sideband_avsbus_octs_bfm_test_seq,
)


@pyuvm.test()
class smc_sideband_avsbus_octs_bfm_test(smc_base_test):
    """P2-A #3: Python fake BFM + CSR scoreboard (does NOT drive DUT pads)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sideband_avsbus_octs_bfm_test_seq("sideband_bfm_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=0,
            proxy=False,
            details=(
                "AVSBus/OCTS CSR + FSM kick + pad49/50 observe + "
                "sdata ACK 0x00FFFF06 + OCTS COUNT + pad58/59 "
                "(dual-chiplet: smc_octs_dual_sync_test)"
            ),
        )
