# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# Goal smc-i2c-fmtrst-repro, reproduction experiment derived from
# smc_i2c_controller_scl_hold_test S1-S2.
# Spec sources: hw/ip/i2c/regs/i2c.rdl TIMEOUT_CTRL, CONTROLLER_EVENTS, INTR_STATE, FIFO_CTRL.
# Fact-recording leaf: the START, CMD_COMPLETE and FDATA-consumed lines carry measured values.
"""I2C0 controller recovery from a bus-timeout halt with FIFO_CTRL.FMTRST.

An external device holds SCL low past TIMEOUT_CTRL.VAL mid-byte, and the
controller halts with CONTROLLER_EVENTS.BUS_TIMEOUT. Two recovery arms follow,
one without and one with a CTRL.ENABLEHOST toggle, each queueing one
START-flagged write. The leaf records whether a START reaches the pads,
whether INTR_STATE.CMD_COMPLETE sets and whether the controller consumes the
FDATA entries.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_fmtrst_repro_test_seq import smc_i2c_fmtrst_repro_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_fmtrst_repro_test(smc_base_test):
    """Bus-timeout halt followed by FMTRST recovery with and without an ENABLEHOST toggle."""

    required_evidence = (
        "CHK-FMTRST-REPRO-START-SEEN",
        "CHK-FMTRST-REPRO-CMD-COMPLETE",
        "CHK-FMTRST-REPRO-FDATA-CONSUMED",
        "CHK-FMTRST-REPRO-START-SEEN-CTRL",
        "CHK-FMTRST-REPRO-CMD-COMPLETE-CTRL",
        "CHK-FMTRST-REPRO-FDATA-CONSUMED-CTRL",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_fmtrst_repro_test_seq("i2c_fmtrst_repro_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
