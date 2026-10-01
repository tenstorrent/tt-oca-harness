# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU-control map depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpu_ctrl_map_depth_test_seq import smc_cpu_ctrl_map_depth_test_seq
from seq_lib.smc_cpu_vip_utils import check_cpu_bfm_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_map_depth_test(smc_base_test):
    """Run CPU-control address-map CSR depth checks."""

    required_evidence = (
        "CHK-CPU-BFM-OBSERVABILITY",
        "CHK-CPU-CTRL-MAP-DEPTH",
        "CHK-CPU-CTRL-MAP-LIVE",
        "CHK-CPU-CTRL-MAP-LOCAL-BASE-RO",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_map_depth_test_seq("cpu_ctrl_map_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        # Gate on the sequence's own conditional evidence token rather than on a
        # relayed boolean: the token is emitted only after every map row's exact
        # RDL-reset compare and the scoreboard reachability cross-check passed.
        assert "CHK-CPU-CTRL-MAP-DEPTH" in seq.chk_seen, (
            f"missing CHK evidence token: CHK-CPU-CTRL-MAP-DEPTH (seen={sorted(seq.chk_seen)})"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 5 SEP_IN AXI SMC_BASE_CONFIG map reads.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=5,
            csr_accesses=seq.accesses,
            proxy=False,
            # This testcase proves SMC_BASE_CONFIG decode + RDL reset content
            # over SEP_IN AXI. The reset/powergood levels checked by
            # `check_cpu_bfm_observability` are a bring-up precondition of that
            # sweep, not part of the map-depth claim.
            details=(
                "SEP_IN AXI SMC_BASE_CONFIG map depth: 5 registers decoded and "
                "compared against their generated RDL reset constants"
            ),
        )
