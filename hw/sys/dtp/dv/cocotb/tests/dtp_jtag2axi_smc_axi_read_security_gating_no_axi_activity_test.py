# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_smc_axi_rd_test_seq import dtp_jtag2axi_smc_axi_rd_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test(dtp_base_test):
    """Run the `read_security_gating_no_axi_activity` SMC fabric JTAG2AXI scenario."""

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_rd_test_seq,
            "read_security_gating_no_axi_activity",
            specific_env="DTP_JTAG2AXI_SMC_AXI_READ_SECURITY_GATING_NO_AXI_ACTIVITY_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="read_security_gating_no_axi_activity",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"read_security_gating_no_axi_activity status {DtpJtag2AxiStatus(seq.status).name}"
            )
