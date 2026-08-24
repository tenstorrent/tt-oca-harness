# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AXI error response depth bounded test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_axi_error_response_depth_test_seq import (
    smc_axi_error_response_depth_test_seq,
)


@pyuvm.test()
class smc_axi_error_response_depth_test(smc_base_test):
    """Run bounded invalid-address probes plus recovery read."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axi_error_response_depth_test_seq("axi_error_response_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "Invalid-address AXI error responses and recovery read checked "
                f"(error_responses={seq.error_responses})"
            ),
        )
