# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold-boot release of the CPU resets and the boundary self-isolation.

Contract SMC_CPU_WEDGE_BOOT_008, anchor smc_cpu_boot_release_sequence_test.
Scenarios CPU-BOOT-FUSE-SENSE-RELEASE.S1-S4, CPU-BOOT-SRAM-INIT.S2, CPU-ISO-COLD-SELF-ISOLATE.S1-S2.
Sources: cpu.adoc (Reset and Boot, Memory Repair, CPU AXI Isolation), clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_boot_release_sequence_test_seq import smc_cpu_boot_release_sequence_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_boot_release_sequence_test(smc_base_test):
    """Per-edge record of the CPU resets, init-done and isolate across two cold resets."""

    required_evidence = (
        "CHK-FUSE-CORES-HELD-UNTIL-SENSE",
        "CHK-FUSE-HELD-WITHOUT-EXT-BOOT",
        "CHK-FUSE-RELEASE-BOTH-TERMS",
        "CHK-FUSE-EXT-BOOT-MID-SENSE",
        "CHK-INIT-MEM-DONE-BYPASS",
        "CHK-COLD-SELF-ISOLATE-HELD",
        "CHK-COLD-SELF-ISOLATE-RELEASE",
        "CHK-NONVAC",
    )
    min_evidence = 8

    async def run_scenario(self) -> None:
        seq = smc_cpu_boot_release_sequence_test_seq("smc_cpu_boot_release_sequence_test_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
