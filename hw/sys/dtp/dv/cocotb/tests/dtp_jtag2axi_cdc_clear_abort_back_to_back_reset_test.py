# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_cdc_clear_abort_back_to_back_reset_test(dtp_base_test):
    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "cdc_clear_abort_back_to_back_reset",
            specific_env="DTP_JTAG2AXI_CDC_CLEAR_ABORT_BACK_TO_BACK_RESET_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="cdc_clear_abort_back_to_back_reset",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"cdc_clear_abort_back_to_back_reset status {DtpJtag2AxiStatus(seq.status).name}"
            )
