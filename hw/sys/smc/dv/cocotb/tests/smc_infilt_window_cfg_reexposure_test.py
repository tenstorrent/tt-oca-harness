# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: TC_M6 ANCHOR: smc_infilt_window_cfg_reexposure_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 21e1e2aab14fedb1b860444fb1238acf0c0f04c182abb98d02234409fe59dacb
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_AXI_FAB_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""SYS_IN through an inbound filter entry whose window covers the filter control and base config.

From SEP_IN the leaf programs inbound entries E (admitting the inbound-filter control aperture
and the base-config block), j, L, U, G and B. Through E, SYS_IN reads entry and base-config
state, writes an unlocked entry, meets a deny entry below and above E, writes the locked entry
L, turns E into a deny entry, writes base-config registers and moves GLOBAL_BASE; through B it
exercises allow_burst and the address granule; the last leg shrinks REGION_SIZE and recovers
with the primary reset. Every answer is graded from a passive per-port handshake sampler, and
decode expectations come from the entry configuration read back from SEP_IN.

Run (VCS: the X-hygiene and data-known rules of the AXI checkers grade on VCS only):
    python3 tools/dv/run_dv.py --dut smc --items smc_infilt_window_cfg_reexposure_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_infilt_window_cfg_reexposure_test_seq import (
    smc_infilt_window_cfg_reexposure_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_infilt_window_cfg_reexposure_test(smc_base_test):
    """Grade SYS_IN reads, writes, locks and self-deny through a window over the filter control."""

    required_evidence = (
        "CHK-FWIN-BASECFG",
        "CHK-FWIN-READ",
        "CHK-FWIN-SELFDENY",
        "CHK-FWIN-WRLOCKED",
        "CHK-FWIN-WRUNLOCKED",
        "CHK-INFILT-BURST",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    async def run_scenario(self) -> None:
        seq = smc_infilt_window_cfg_reexposure_test_seq("infilt_window_cfg_reexposure_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        try:
            await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        except BaseException:
            seq.log_timeout_paths()
            seq.nonvac_fence(check=False)
            raise
        seq.log_timeout_paths()
        seq.nonvac_fence()
        seq.raise_findings()
