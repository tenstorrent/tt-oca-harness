# SPDX-License-Identifier: Apache-2.0
"""SMC OSS zeroer datapath payload test.

DV-CARD:          SMC_006   ANCHOR: smc_zeroer_dma_timeout_test
DV-CARD-REVISION: 2   RECORD-SHA256: 8434b5884c73c281ef8ebefa9a3a1aa867a172be603a87301d97408f42460538
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_zeroer_dma_timeout_test_seq import smc_zeroer_dma_timeout_test_seq


@pyuvm.test()
class smc_zeroer_dma_timeout_test(smc_base_test):
    """Run zeroer over output-fabric payload bytes and check the model."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_dma_timeout_test_seq("zeroer_dma_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "Zeroer cleared output-fabric payload via JTAG AXI readback "
                f"(checked_bytes={seq.checked_bytes}; neighbour poison unchanged)"
            ),
        )
