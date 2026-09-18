# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_otp_axi_test_seq import dtp_jtag2axi_otp_axi_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test(dtp_base_test):
    # Shared AXI checker: passive bus monitors + reference model compare every
    # observed transaction; the required evidence IDs and per-stream minimum
    # compared-transaction counts below make a silent no-op run fail at
    # finalization.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-STATUS-BIT",
    )
    axi_checker_stream_minimums = {"smc_otp": 2}

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_otp_axi_test_seq,
            "smc_otp_series_write_incr_with_error",
            specific_knob="DTP_JTAG2AXI_SMC_OTP_AXI_SERIES_WRITE_INCR_WITH_ERROR_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="smc_otp",
            scenario="series_write_incr_with_error",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"smc_otp series_write_incr_with_error status {DtpJtag2AxiStatus(seq.status).name}"
            )
