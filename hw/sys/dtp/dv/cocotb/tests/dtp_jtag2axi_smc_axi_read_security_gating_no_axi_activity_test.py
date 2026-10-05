# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test`."""

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DtpJtag2AxiStatus
from seq_lib.dtp_jtag2axi_smc_axi_rd_test_seq import dtp_jtag2axi_smc_axi_rd_test_seq


@pyuvm.test()
class dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test(dtp_base_test):
    """Run the `read_security_gating_no_axi_activity` SMC fabric JTAG2AXI scenario."""

    # Security gating is a deterministic must-NOT-happen property checked per
    # lifecycle bit with baseline/restore
    # positive controls; randomized read traffic on the same port lives in
    # dtp_jtag2axi_smc_axi_read_random_ops_test.
    #
    # Shared AXI checker: gated attempts must show zero request activity
    # (pulse counters plus a blocked window held across lifecycle re-enable,
    # and an exact activity delta through the restore read), while
    # baseline/restore reads prove the observation path is alive.
    use_axi_scoreboard = True
    axi_checker_required_ids = (
        "CHK-AXI-NOACT",
        "CHK-AXI-RESP",
        "CHK-AXI-RDATA",
        "CHK-AXI-COMPLETION",
        "CHK-AXI-STREAM-MIN",
        "CHK-AXI-NONVAC",
        "CHK-J2A-GATE-TDR",
    )
    axi_checker_stream_minimums = {"smc_axi": 2}

    async def run_scenario(self) -> None:
        sequences = await self.start_looped_seq(
            dtp_jtag2axi_smc_axi_rd_test_seq,
            "read_security_gating_no_axi_activity",
            specific_knob="DTP_JTAG2AXI_SMC_AXI_READ_SECURITY_GATING_NO_AXI_ACTIVITY_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_JTAG2AXI_TEST_LOOPS",
            scenario="read_security_gating_no_axi_activity",
        )
        for seq in sequences:
            assert seq.status == DtpJtag2AxiStatus.SUCCESS, (
                f"read_security_gating_no_axi_activity status {DtpJtag2AxiStatus(seq.status).name}"
            )
