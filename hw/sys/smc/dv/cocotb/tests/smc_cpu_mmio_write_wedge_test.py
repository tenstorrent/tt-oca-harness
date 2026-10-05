# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MMIO write drain and stale response recover across a forced CPU reset."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_isolate_flush_test_seq import smc_cpu_mmio_write_wedge_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_mmio_write_wedge_test(smc_base_test):
    """Withhold SYS_OUT B, force reset, absorb it, and reboot firmware."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-CPU-ISO-FLUSH-DRAINED-WHILE-BLOCKED",
        "CHK-CPU-ISO-FLUSH-FORCED-RESET",
        "CHK-CPU-ISO-FLUSH-FRONT-PORT-RECOVERED",
        "CHK-CPU-ISO-FLUSH-FW-RECOVERED",
        "CHK-CPU-ISO-FLUSH-STALE-RESP-ABSORBED",
    )
    min_evidence = 5

    async def run_scenario(self) -> None:
        seq = smc_cpu_mmio_write_wedge_test_seq("cpu_mmio_write_wedge_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.contracts == {
            "forced_reset",
            "drained_while_blocked",
            "stale_response_absorbed",
            "firmware_recovered",
            "front_port_recovered",
        }, f"incomplete MMIO write recovery contracts: {sorted(seq.contracts)}"
