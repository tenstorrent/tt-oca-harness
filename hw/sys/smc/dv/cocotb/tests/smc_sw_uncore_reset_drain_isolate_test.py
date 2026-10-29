# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_003 ANCHOR: smc_sw_uncore_reset_drain_isolate_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 89c23b57e53913867731dea0e63164d785460cb5be5e0c3dd67a2bd39a962388
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Software core reset, core reset pulse and software uncore reset with the L2 frontend isolate.

RESET_CTRL is written over SEP_IN: core 3 is held and pulsed without a drain, the uncore bit is
cleared with four L2 frontend reads parked in timer-off, give-up and force modes, reads presented
on SEP_IN, SYS_IN and JTAG_IN while the boundary is isolated are blocked until the reconnect, and
a cold reset replayed through the reset agent ends the leaf. The sequence docstring gives the
graded claims and the observation-only lines.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_sw_uncore_reset_drain_isolate_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_sw_uncore_reset_drain_isolate_test_seq import (
    smc_sw_uncore_reset_drain_isolate_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_sw_uncore_reset_drain_isolate_test(smc_base_test):
    """Software core and uncore resets with the drain handshake and the L2 frontend isolate."""

    required_evidence = (
        "CHK-BLOCKED-NOT-TERMINATED-THEN-RECONNECT",
        "CHK-COLD-ISOLATION-RELEASE",
        "CHK-CORE-HOLD-NO-DRAIN",
        "CHK-CORE-PULSE",
        "CHK-CORE-RESET-N-TERM",
        "CHK-CORE3-WDT-CONFIG",
        "CHK-DRAIN-HANDSHAKE-ORDER",
        "CHK-DRAIN-PENDING-READS-COMPLETE",
        "CHK-FORCE-MODE-REQUEST-STATUS",
        "CHK-GIVEUP-REPORT-AND-WAIT",
        "CHK-L2F-FOUR-OUTSTANDING",
        "CHK-NONVAC",
        "CHK-OBS-CORE-RESET-ACCESS",
        "CHK-OBS-DRAIN-FLUSH-RESPONSES",
        "CHK-OBS-ISOLATION-DELAY",
        "CHK-OBS-MMIO-RESET",
        "CHK-OBS-PULSE-AND-STATUS",
        "CHK-OBS-TIMEOUT-EXPIRY",
        "CHK-STATUS-READABLE-FROM-SEP",
        "CHK-TIMEOUT-PATHS",
        "CHK-TIMER-OFF-WAITS",
        "CHK-VALID-LOW-UNCORE-SW",
    )
    min_evidence = 22

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sw_uncore_reset_drain_isolate_test_seq("sw_uncore_reset_drain_isolate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
