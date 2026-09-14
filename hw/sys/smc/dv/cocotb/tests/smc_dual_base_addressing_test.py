# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Local alias base is fixed read-only; the global base is programmable.

Closes SMC-MAP-DUALBASE.S1 (memmap.adoc: Memory Map): LOCAL_BASE reads
0xC000_0000 and keeps that value across a write attempt, while GLOBAL_BASE in
the same register block takes and returns a pattern through the identical
write path; REGION_SIZE reads its specified 16 MiB reset. The
``smc_region_size_o`` pin is unconnected in ``tb_top`` and is not claimed.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_dual_base_addressing_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dual_base_addressing_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_dual_base_addressing_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dual_base_addressing_test(smc_base_test):
    """LOCAL_BASE read-only at 0xC000_0000, GLOBAL_BASE programmable."""

    required_evidence = (
        "CHK-DUAL-BASE",
        "CHK-DUAL-BASE-ADDRESSING",
        "CHK-DUAL-BASE-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dual_base_addressing_test_seq("dual_base_addressing_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-DUAL-BASE-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d",
            value_compares,
            EXPECTED_VALUE_CHECKS,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_ACCESSES,
            proxy=False,
            details=(
                f"LOCAL_BASE/GLOBAL_BASE/REGION_SIZE over SEP_IN AXI: {seq.accesses} accesses, "
                f"{value_compares} exact-value compares"
            ),
        )
