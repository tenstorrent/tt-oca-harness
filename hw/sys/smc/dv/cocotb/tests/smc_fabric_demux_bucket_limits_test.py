# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The fabric demultiplexers withhold the same-ID read past their stated bucket limit.

Spec source: fabric.adoc SMC Fabric Transaction Limits.

Reproducer for the vendored `axi_demux` counter width, which admits `MaxTrans - 1` per ID
bucket; enrolled as `rtl_issue` under `expect_fail`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fabric_demux_bucket_limits_test_seq import (
    smc_fabric_demux_bucket_limits_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fabric_demux_bucket_limits_test(smc_base_test):
    """RREADY-held same-ID read groups past the demux bucket limits of 32 and 8."""

    required_evidence = (
        "CHK-FABRIC-33RD-WAITS-FOR-RETIRE",
        "CHK-LOCAL-XBAR-9TH-WAITS",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_fabric_demux_bucket_limits_test_seq("smc_fabric_demux_bucket_limits_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.raise_fails()
