# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI checking across a CPU-only core reset and a watchdog warm reset with transactions open.

Boots the hello_world image, then runs two partial resets with transactions
open on the links around them: a core 0 reset through CPU_CTRL RESET_CTRL with
SEP_IN and SYS_IN cluster-memory reads parked, and a SEP-watchdog warm reset
with SEP_IN reads and SYS_OUT writes open on cold-domain targets. The bench's
twelve ocah_axi_sva instances stay on throughout, two of them on the link's
own partial reset; +axi_sva_need_<port> makes each named checker prove it
graded traffic.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=hello_world.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_sys_axi_agent import idle_axil_master_inputs
from seq_lib.smc_axi_partial_reset_open_txn_test_seq import (
    smc_axi_partial_reset_open_txn_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_partial_reset_open_txn_test(smc_base_test):
    """Open transactions across the CPU-only and the watchdog warm reset, every checker on."""

    required_evidence = (
        "CHK-G2-ALL-SILENT",
        "CHK-G2-CORE-HELD-TRAFFIC",
        "CHK-G2-LIVENESS",
        "CHK-G2-PRIMARY-RECONCILED",
        "CHK-G2-RESET-VALID-LOW",
        "CHK-G2-TRACK-CLEARED",
        "CHK-G2-WARM-ENTRY",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        idle_axil_master_inputs(cocotb.top, "ej_axi")
        seq = smc_axi_partial_reset_open_txn_test_seq("axi_partial_reset_open_txn_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.expired == 0 and seq.waits > 0, (
            f"bounded waits {seq.waits}, expired {seq.expired}"
        )
