# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller role gate: a queued FMT stream runs only once CTRL.ENABLEHOST is set."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_ctrl_role_gate_test_seq import smc_i2c_ctrl_role_gate_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_ctrl_role_gate_test(smc_base_test):
    """Queue three FDATA entries with the roles off, enable the controller, observe the stream."""

    required_evidence = (
        "CHK-FMTEMPTY-TRACK",
        "CHK-IEN-ROLE-INDEP",
        "CHK-NONVAC",
        "CHK-ROLE-OFF-IDLE",
        "CHK-ROLE-ON-RUNS",
        "CHK-TIMEOUT-PATHS",
        "CHK-VAL-OBS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_ctrl_role_gate_test_seq("i2c_ctrl_role_gate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
