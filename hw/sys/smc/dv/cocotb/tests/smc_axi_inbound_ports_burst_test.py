# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Full-width and INCR burst traffic on SEP_IN, SYS_IN and JTAG, and bursts at register islands."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axi_inbound_ports_burst_test_seq import (
    smc_axi_inbound_ports_burst_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_inbound_ports_burst_test(smc_base_test):
    """8-byte round trips and 2/4/16/256-beat INCR bursts into the SPM on every inbound port."""

    required_evidence = (
        "CHK-IPB-INCR-256",
        "CHK-IPB-INCR-MEMORY",
        "CHK-IPB-INCR-REG-OBS",
        "CHK-IPB-REJECT-READ-OBS",
        "CHK-IPB-REJECT-RECOVERY",
        "CHK-IPB-WIDTH-ROUNDTRIP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axi_inbound_ports_burst_test_seq("axi_inbound_ports_burst_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses > 0 and all(seq.port_accesses.values()), (
            f"a port issued no access: {seq.port_accesses}"
        )
