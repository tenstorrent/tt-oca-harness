# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_error_series_incr_write_with_status_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_error_test_seq import dtp_jtag2axi_error_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_error_series_incr_write_with_status_test(dtp_base_test):
    # Shared AXI checker: passive bus monitors + reference model compare every
    # observed transaction; the required evidence IDs and per-stream minimum
    # compared-transaction counts below make a silent no-op run fail at
    # finalization.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RESP-EXPECTED",
        "CHK-AXI-STRB",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-CREDITS",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_error_test_seq,
            "smc_axi_error_series_incr_write_with_status",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_ERROR_SERIES_INCR_WRITE_WITH_STATUS_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            target="smc_axi",
            scenario="error_series_incr_write_with_status",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"smc_axi error_series_incr_write_with_status status {DtpJtag2AxiStatus(seq.status).name}"
            )
