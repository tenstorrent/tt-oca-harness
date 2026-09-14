# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_series_write_read_incr_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_smc_axi_rd_test_seq import dtp_jtag2axi_smc_axi_rd_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_series_write_read_incr_test(dtp_base_test):
    """Run the `series_write_read_incr` SMC fabric JTAG2AXI scenario."""

    # Shared AXI checker: passive bus monitors + reference model compare every
    # observed transaction; the required evidence IDs and per-stream minimum
    # compared-transaction counts below make a silent no-op run fail at
    # finalization.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_rd_test_seq,
            "series_write_read_incr",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_SERIES_WRITE_READ_INCR_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="series_write_read_incr",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"series_write_read_incr status {DtpJtag2AxiStatus(seq.status).name}"
            )
