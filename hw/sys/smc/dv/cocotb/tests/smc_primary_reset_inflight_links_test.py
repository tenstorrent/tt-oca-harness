# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_001 ANCHOR: smc_primary_reset_inflight_links_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 76b6465141e11bd6f19e49d95a2aa9b35227743cd71a3128192bf598cc33d8cc
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Primary reset with accesses pending on every steerable AXI link, entered three ways.

The cool pin, the JTAG cool override and the FLR timed cool reset each land while reads and
a write are outstanding on SEP_IN, SYS_IN, JTAG_IN and SYS_OUT, the eFuse JTAG AXI-Lite port
and the peripheral crossbar, and a read of the DTP CSR window sits in its request phase. The
sequence docstring gives the graded claims and the observation-only lines.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_primary_reset_inflight_links_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_primary_reset_inflight_links_test_seq import (
    smc_primary_reset_inflight_links_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_primary_reset_inflight_links_test(smc_base_test):
    """Cool pin, JTAG cool override and FLR cool reset with a pending set on every link."""

    required_evidence = (
        "CHK-COOL-GLITCH-NO-ASSERT",
        "CHK-COOL-PIN-PRIMARY-EFFECTS",
        "CHK-DTP-LINK-REQUEST-PHASE",
        "CHK-FLR-ENTRY-PRIMARY",
        "CHK-FRESH-ACCESS-EFUSE-JTAG",
        "CHK-FRESH-ACCESS-JTAG-IN",
        "CHK-FRESH-ACCESS-PERIPH",
        "CHK-FRESH-ACCESS-SEP-IN",
        "CHK-FRESH-ACCESS-SYS-IN",
        "CHK-FRESH-ACCESS-SYS-OUT",
        "CHK-INFLIGHT-AT-ASSERT",
        "CHK-JTAG-COOL-OVERRIDE-ENTRY",
        "CHK-NO-ORPHAN-RESPONSE",
        "CHK-NONVAC",
        "CHK-OBS-JTAG-OVERRIDE-ORDER",
        "CHK-OBS-PHASE-FATE",
        "CHK-OBS-RELEASE-LATENCY",
        "CHK-OBS-VALID-FIRST-EDGE",
        "CHK-TIMEOUT-PATHS",
        "CHK-VALID-LOW-CLUSTER",
        "CHK-VALID-LOW-DTP",
        "CHK-VALID-LOW-INBOUND",
        "CHK-VALID-LOW-SYS-OUT",
    )
    min_evidence = 23

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_primary_reset_inflight_links_test_seq("primary_reset_inflight_links_seq")

        async def _dispatch(item) -> None:
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = _dispatch
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        aborted = self.env.scoreboard.sys_axi_reset_aborted_seen
        assert aborted == seq.expected_aborted_items, (
            f"scoreboard booked {aborted} sequencer accesses abandoned by the reset, expected "
            f"{seq.expected_aborted_items}"
        )
