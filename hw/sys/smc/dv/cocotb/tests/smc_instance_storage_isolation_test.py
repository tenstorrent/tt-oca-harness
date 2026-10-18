# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Instance isolation of the scratch, remap, filter and GPIO register arrays.

Spec sources: scratch.rdl SCRATCH[8]; misc_wrap.rdl scratch_cold; smc.rdl register arrays.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_instance_storage_isolation_test_seq import (
    ACCESS_FLOOR,
    PORTS,
    smc_instance_storage_isolation_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ALIAS-REMAP-ISOLATION",
    "CHK-FILTER-CTRL-ISOLATION",
    "CHK-GPIO-INSTANCE-ISOLATION",
    "CHK-NONVAC",
    "CHK-OUTPUT-REMAP-ISOLATION",
    "CHK-SCRATCH-32BIT-PORTS",
    "CHK-SCRATCH-COLD-ISOLATION",
    "CHK-SCRATCH-COLD-WARM-SEPARATE",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_instance_storage_isolation_test(smc_base_test):
    """Write-all-then-read-all of every instance of each register array."""

    required_evidence = REQUIRED
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_instance_storage_isolation_test_seq("instance_storage_isolation_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert sum(seq.port_accesses.values()) >= ACCESS_FLOOR, "access count below the floor"
        by_bus = self.env.scoreboard.axi_accesses_by_bus
        for port, bus in zip(PORTS, ("SEP_IN AXI", "SYS_IN AXI", "JTAG AXI")):
            seen = by_bus.get(bus, 0)
            assert seen >= seq.port_accesses[port], (
                f"{bus}: scoreboard counted {seen}, sequence issued {seq.port_accesses[port]}"
            )
