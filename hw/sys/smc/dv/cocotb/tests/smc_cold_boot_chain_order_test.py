# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold boot chain runs in order and the cluster self-isolates until it is ready.

Closes the observable cells of INT-POR-BOOT, SMC-CLUSTER-ISO.S6 and
SMC-CLUSTER-ISO.S7 (cpu.adoc: Memory Repair, CPU AXI Isolation;
rom.adoc: Boot ROM; clk_rst.adoc: Reset Architecture): a second cold reset is
driven through the reset agent and every boundary observable is stamped on one
clk_smc_i timeline -- power-good stable before fuse sense, fuse sense before
the core reset release, the first retired instruction at the specified ROM
vector, and cluster isolation held from the cold pin until after both
smc_init_mem_done_o and the core reset release. SMC-MEMREPAIR.S1 and
SMC-SRAM-INIT.S1 are not closed: this bench ties the repair/MBIST done inputs
and smc_disable_sram_auto_init_i, so neither engine runs.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_cold_boot_chain_order_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_cold_boot_chain_order_test_seq import smc_cold_boot_chain_order_test_seq
from smc_base_test import smc_base_test

EXPECTED_WAIT_CHECKS = 2


@pyuvm.test()
class smc_cold_boot_chain_order_test(smc_base_test):
    """Boot-chain ordering and the cluster self-isolation window on a cold reset."""

    required_evidence = (
        "CHK-CLUSTER-SELF-ISOLATED-AT-COLD-BOOT",
        "CHK-COLD-BOOT-CHAIN",
        "CHK-COLD-BOOT-FIRST-FETCH-AT-ROM-VECTOR",
        "CHK-COLD-BOOT-NOT-CLOSED",
        "CHK-COLD-BOOT-ORDER",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    async def run_scenario(self) -> None:
        seq = smc_cold_boot_chain_order_test_seq("cold_boot_chain_order_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= EXPECTED_WAIT_CHECKS, (
            f"scoreboard booked {sb.reset_wait_checks_seen} reset WAIT_STATE checks, expected at "
            f"least {EXPECTED_WAIT_CHECKS}"
        )
        assert seq.reset_levels_seen and seq.first_fetch_cycle is not None, (
            "the sequence ended without observing the reset levels and a first fetch"
        )
        cocotb.log.info(
            "CHK-COLD-BOOT-CHAIN: stamps %s first_fetch=%d pc=0x%x; scoreboard reset wait checks %d",
            seq.stamps,
            seq.first_fetch_cycle,
            seq.first_fetch_pc,
            sb.reset_wait_checks_seen,
        )
