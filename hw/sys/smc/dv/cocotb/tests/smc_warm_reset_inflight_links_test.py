# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_002 ANCHOR: smc_warm_reset_inflight_links_test
# DV-TESTCASE-CONTRACT-REVISION: 5 RECORD-SHA256: ee66ec136cc40520ee3b583fa72c0439bf9680d9f9e962afad4ee03706e6d996
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Warm reset through the watchdog input and the JTAG override with accesses pending on every link.

The watchdog reset input lands while reads and a write are outstanding on SEP_IN, SYS_IN,
JTAG_IN and SYS_OUT, the eFuse JTAG AXI-Lite port and the peripheral crossbar; the cold reset
the TRM requires after a watchdog timeout, the JTAG warm override, the armed core-3 watchdog
second stage and a reprogrammed core-3 reset vector follow. The sequence docstring gives the
graded claims and the observation-only lines.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_warm_reset_inflight_links_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_warm_reset_inflight_links_test_seq import (
    smc_warm_reset_inflight_links_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_warm_reset_inflight_links_test(smc_base_test):
    """Watchdog-input and JTAG-override warm resets with a pending set on every link."""

    required_evidence = (
        "CHK-CTRL-REGS-KEPT-ACROSS-WARM",
        "CHK-FRESH-ACCESS-EFUSE-JTAG-WARM",
        "CHK-FRESH-ACCESS-JTAG-IN-WARM",
        "CHK-FRESH-ACCESS-PERIPH-WARM",
        "CHK-FRESH-ACCESS-SEP-IN-WARM",
        "CHK-FRESH-ACCESS-SYS-IN-WARM",
        "CHK-FRESH-ACCESS-SYS-OUT-WARM",
        "CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM",
        "CHK-JTAG-WARM-OVERRIDE-ENTRY",
        "CHK-NO-DRAIN-ON-WARM",
        "CHK-NO-ORPHAN-RESPONSE-WARM",
        "CHK-NONVAC",
        "CHK-OBS-ATTRIBUTES",
        "CHK-OBS-FUSE-WINDOW-ACCESS",
        "CHK-OBS-WARM-CLUSTER-VALIDS",
        "CHK-OBS-WARM-ISOLATE-STATE",
        "CHK-OBS-WARM-PHASE-FATE",
        "CHK-OBS-WARM-VECTOR",
        "CHK-OBS-WARM-WEDGE-AFTER-WDT",
        "CHK-OBS-WARM-WINDOW-ACCESS",
        "CHK-TIMEOUT-PATHS",
        "CHK-WARM-FUSE-ALONE",
        "CHK-WARM-HOLDS-CPU",
        "CHK-WARM-SCRATCH-RESET",
        "CHK-WDT-INPUT-WARM-ONLY",
        "CHK-WDT-LATCH-NOT-WITHDRAWN",
        "CHK-WDT-SECOND-STAGE-WARM",
    )
    min_evidence = 27

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_warm_reset_inflight_links_test_seq("warm_reset_inflight_links_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
