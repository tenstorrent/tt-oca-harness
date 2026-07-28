# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_jtag2axi_backpressure_aw_before_w_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_backpressure_aw_before_w_test(dtp_base_test):
    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "backpressure_aw_before_w",
            specific_env="DTP_JTAG2AXI_BACKPRESSURE_AW_BEFORE_W_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="backpressure_aw_before_w",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"backpressure_aw_before_w status {DtpJtag2AxiStatus(seq.status).name}"
            )
