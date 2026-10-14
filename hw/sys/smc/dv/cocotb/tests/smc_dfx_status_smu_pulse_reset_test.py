# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STATUS_SMU independence, reserved bits, pulses, resets and read-only writes.

Spec: dfx_ctrl_status.rdl STATUS, memmap.adoc DFX Status, clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfx_status_smu_pulse_reset_test_seq import (
    smc_dfx_status_smu_pulse_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfx_status_smu_pulse_reset_test(smc_base_test):
    """STATUS_SMU abort bits: independence, reserved bits, pulse capture, resets, RO writes."""

    required_evidence = (
        "CHK-DFX-STATUS-HIGH-THROUGH-RESET",
        "CHK-DFX-STATUS-MBIST-ALONE",
        "CHK-DFX-STATUS-PULSE",
        "CHK-DFX-STATUS-RESERVED",
        "CHK-DFX-STATUS-RESET-CLEARS",
        "CHK-DFX-STATUS-RO-CLEAN",
        "CHK-DFX-STATUS-RO-SET",
        "CHK-DFX-STATUS-STAGGER",
        "CHK-DFX-STATUS-WRITE-RESP",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_status_smu_pulse_reset_test_seq("dfx_status_smu_pulse_reset_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
