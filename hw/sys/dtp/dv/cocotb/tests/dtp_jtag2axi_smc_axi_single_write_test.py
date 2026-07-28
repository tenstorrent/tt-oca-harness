# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_single_write_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_smc_axi_wr_test_seq import dtp_jtag2axi_smc_axi_wr_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_single_write_test(dtp_base_test):
    """Run the `single_write` SMC fabric JTAG2AXI scenario."""

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_wr_test_seq,
            "single_write",
            specific_env="DTP_JTAG2AXI_SMC_AXI_SINGLE_WRITE_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="single_write",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"single_write status {DtpJtag2AxiStatus(seq.status).name}"
            )
