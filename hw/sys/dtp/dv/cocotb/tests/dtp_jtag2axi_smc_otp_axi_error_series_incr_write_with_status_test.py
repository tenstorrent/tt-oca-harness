# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_otp_axi_error_series_incr_write_with_status_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_error_test_seq import dtp_jtag2axi_error_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_otp_axi_error_series_incr_write_with_status_test(dtp_base_test):
    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_error_test_seq,
            "smc_otp_error_series_incr_write_with_status",
            specific_env="DTP_JTAG2AXI_SMC_OTP_AXI_ERROR_SERIES_INCR_WRITE_WITH_STATUS_TEST_LOOPS",
            default_loops=1,
            group_env="DTP_JTAG2AXI_TEST_LOOPS",
            target="smc_otp",
            scenario="error_series_incr_write_with_status",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"smc_otp error_series_incr_write_with_status status {DtpJtag2AxiStatus(seq.status).name}"
            )
