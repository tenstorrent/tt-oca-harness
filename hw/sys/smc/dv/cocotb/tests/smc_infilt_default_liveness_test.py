# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound filter blocks SYS_IN by default and stays live across enable and reconfig."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_infilt_default_liveness_test_seq import (
    _SYS_ACCESSES,
    smc_infilt_default_liveness_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_default_liveness_test(smc_base_test):
    """SYS_IN is blocked at reset, admitted by entry 2, denied by entry 1 and flooded."""

    required_evidence = (
        "CHK-INB-ADMIT-AFTER-DENY",
        "CHK-INB-DENY-FLOOD",
        "CHK-INB-ENABLE-LIFECYCLE",
        "CHK-INB-READ-FILTER-CONFIG",
        "CHK-INB-RECONFIG-OUTSTANDING",
        "CHK-INB-RESET-BLOCKS-SYS-IN",
        "CHK-INB-SEP-NOT-FILTERED",
        "CHK-INB-SIMULTANEOUS-PORTS",
        "CHK-INB-UNMATCHED-STAYS-BLOCKED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_infilt_default_liveness_test_seq("smc_infilt_default_liveness_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.sys_accesses == _SYS_ACCESSES, (
            f"{seq.sys_accesses} SYS_IN accesses issued, want {_SYS_ACCESSES}"
        )
        measured = self.env.scoreboard.axi_accesses_by_bus
        assert measured.get("SYS_IN AXI", 0) == _SYS_ACCESSES, (
            f"scoreboard saw {measured.get('SYS_IN AXI', 0)} SYS_IN accesses, want {_SYS_ACCESSES}"
        )
        assert measured.get("SEP_IN AXI", 0) >= seq.accesses, (
            f"scoreboard saw {measured.get('SEP_IN AXI', 0)} SEP_IN accesses, "
            f"sequence issued {seq.accesses}"
        )
