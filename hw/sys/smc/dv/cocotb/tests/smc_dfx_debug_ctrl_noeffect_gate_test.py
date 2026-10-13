# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DEBUG_CTRL no-effect fields, bit 31, DFD observables and register access around cg_en.

Contract SMC_JTAG_DM_021, anchor smc_dfx_debug_ctrl_noeffect_gate_test.
Scenarios JDM-DFX-DEBUGCTRL-NOEFFECT.S1 .. S4, JDM-DFX-CLKGATE.S5 and S7.
Spec: dfx_ctrl_status.rdl DEBUG_CTRL, dfd.adoc Design-for-Debug,
memmap.adoc Base Config and DFX Status.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfx_debug_ctrl_noeffect_gate_test_seq import (
    smc_dfx_debug_ctrl_noeffect_gate_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfx_debug_ctrl_noeffect_gate_test(smc_base_test):
    """DEBUG_CTRL no-effect readback, cold reset, DFD probes and cg_en access liveness."""

    required_evidence = (
        "CHK-DEBUGCTRL-FIELD-HOLD",
        "CHK-DEBUGCTRL-EFFECT-CLEAR",
        "CHK-DEBUGCTRL-RESET-BIT31",
        "CHK-DEBUGCTRL-NO-OBSERVABLE",
        "CHK-CLKGATE-INFLIGHT",
        "CHK-CLKGATE-STATUS-ACCESS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfx_debug_ctrl_noeffect_gate_test_seq("dfx_debug_ctrl_noeffect_gate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
