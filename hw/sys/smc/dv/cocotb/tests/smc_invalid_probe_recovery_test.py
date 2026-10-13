# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Valid-access recovery after runs of outside-window, gap and past-extent DECERR probes.

Contract XBAR_030, anchor smc_invalid_probe_recovery_test.
Allocated scenarios: XBAR-RECOVERY.S1-S3, XBAR-GAP-DECERR.S5.
Spec sources: memmap.adoc Address Space Organization, fabric.adoc Fabric Transaction Limits.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_invalid_probe_recovery_test_seq import smc_invalid_probe_recovery_test_seq
from smc_base_test import smc_base_test

# Accesses the sequence issues: setup 3 writes + 1 admit read, outside runs 2 ports x
# (66 probes + 9 valid reads), gap runs 3 ports x (66 probes + 3 valid reads), write-readback
# 6, mixed run 33, filter restore 6.
STIMULUS_FLOOR = 4 + 2 * (66 + 9) + 3 * (66 + 3) + 6 + 33 + 6


@pyuvm.test()
class smc_invalid_probe_recovery_test(smc_base_test):
    """Valid accesses answer OKAY after DECERR probe runs of 1, 32 and 33 on every inbound port."""

    required_evidence = (
        "CHK-RECOVERY-OUTSIDE-WINDOW",
        "CHK-RECOVERY-GAP-PAST-EXTENT",
        "CHK-RECOVERY-WRITE-READBACK",
        "CHK-GAP-RUN-BOUNDED",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_invalid_probe_recovery_test_seq("invalid_probe_recovery_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "INVALID_PROBE_RECOVERY")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
