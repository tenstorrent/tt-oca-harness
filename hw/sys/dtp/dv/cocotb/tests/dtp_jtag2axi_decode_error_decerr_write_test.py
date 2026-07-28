# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_jtag2axi_decode_error_decerr_write_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_robustness_test_seq import dtp_jtag2axi_robustness_test_seq


@pyuvm.test()
class dtp_jtag2axi_decode_error_decerr_write_test(dtp_base_test):
    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_robustness_test_seq,
            "decode_error_decerr_write",
            specific_env="DTP_JTAG2AXI_DECODE_ERROR_DECERR_WRITE_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="decode_error_decerr_write",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"decode_error_decerr_write status {DtpJtag2AxiStatus(seq.status).name}"
            )
