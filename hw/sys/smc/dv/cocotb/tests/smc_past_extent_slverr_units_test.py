# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_R4_003 ANCHOR: smc_past_extent_slverr_units_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 6be46fedcec884c50cdbb8daa6cb4ee084f440621197d483c8c35006e003758b
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_R4_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""Past-extent, last-aperture-word and unimplemented-offset responses of SMC unit windows.

The past-extent legs of the SLVERR-declared units and the UART/log-engine wrappers run
first; then each of the CLA, DMA-control, zeroer-control, UART, log-engine, eFuse control,
eFuse shadow, I3C, telemetry, AVSBus and external windows takes one read and one write at an
unimplemented offset inside the window, followed by an OKAY access on the same path.

Spec sources: smc.rdl ocah_past_extent_resp placements, misc_wrap.rdl ocah_gap_resp,
memmap.adoc, memory_map.adoc component rows, uart_log_engine_wrap.adoc, uart_16550_main.adoc,
log_engine.adoc, smc_cla.adoc, zeroer_ctrl.adoc, efuse_interface_ctrl.adoc and
telemetry_receiver.adoc.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_past_extent_slverr_units_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_past_extent_slverr_units_test_seq import (
    smc_past_extent_slverr_units_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 1; past-extent legs: reset unit 7, eFuse 14, timer 7,
# base config 10, fabric arrays 35, spare wrapper 25, peripherals 4 x 7 + UART and I3C 2 x 2,
# CLA 3, UART/log-engine wrappers 36; window probes: CLA 10, DMA 3 + zeroer 5, UART 6 +
# log engine 8, eFuse 6, I3C 3, telemetry 5 + AVSBus 3, external 4.
STIMULUS_FLOOR = 223
# The UART and I3C aperture-end reads bypass the driver, so the scoreboard sees the rest.
UNCONVERTED_READS = 2
SCOREBOARD_ACCESSES = STIMULUS_FLOOR - UNCONVERTED_READS


@pyuvm.test()
class smc_past_extent_slverr_units_test(smc_base_test):
    """Past-extent and unimplemented-offset responses of the SMC unit windows over SEP_IN."""

    required_evidence = (
        "CHK-ERR-AVS",
        "CHK-ERR-CLA",
        "CHK-ERR-DMA",
        "CHK-ERR-EFUSE",
        "CHK-ERR-EXTERNAL",
        "CHK-ERR-I3C",
        "CHK-ERR-LOGENG",
        "CHK-ERR-TELEMETRY",
        "CHK-ERR-UART",
        "CHK-ERR-ZEROER",
        "CHK-NONVAC",
        "CHK-PAST-EXTENT-BASE-CONFIG",
        "CHK-PAST-EXTENT-CLA",
        "CHK-PAST-EXTENT-EFUSE",
        "CHK-PAST-EXTENT-FABRIC-CTRL",
        "CHK-PAST-EXTENT-PERIPH",
        "CHK-PAST-EXTENT-RESET-UNIT",
        "CHK-PAST-EXTENT-SPARE",
        "CHK-PAST-EXTENT-TIMER",
        "CHK-PAST-EXTENT-UARTWRAP",
        "CHK-PAST-EXTENT-UARTWRAP-LIVE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 22

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_past_extent_slverr_units_test_seq("past_extent_slverr_units_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.unconverted_reads == UNCONVERTED_READS, (
            f"{seq.unconverted_reads} unconverted reads, want {UNCONVERTED_READS}"
        )
        seq.assert_all_reachable(SCOREBOARD_ACCESSES, "PAST_EXTENT_SLVERR_UNITS")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
