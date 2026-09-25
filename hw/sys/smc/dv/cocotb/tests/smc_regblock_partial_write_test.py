# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte writes that hold set fields, W1C fields held across a zero, and zero writes.

`I2C_CTRL.SMBUS_EN` (three instances) and I2C0 `SMBUS_CTRL.SMBALERT` must hold
across a byte write to another lane. Six I2C0 `INTR_STATE` events and the log
engine's `LOG_FETCH_ERR` are raised through `INTR_TEST`; each must survive a
write of zero and clear on a one. Zero writes to log-engine `INTR_TEST`, OCTS
`TIMER_START` and telemetry `INTR_STATUS` must change nothing. A write resets
OCTS `CREDIT_EXPIRED`, and I2C0 `TARGET_NACK_COUNT` reads 0 at idle.
Telemetry `TX_FLUSH` must hold across a lane-0 byte write while AFREADY is held
low, and a byte write at UART0 FCR+1 must leave `IIR` unchanged.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_regblock_partial_write_test_seq import (
    NUM_I2C_CTRL,
    smc_regblock_partial_write_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_regblock_partial_write_test(smc_base_test):
    """Partial and zero writes leave set fields and triggers alone."""

    required_evidence = (
        "CHK-REGBLOCK-DOCUMENTED-WRITE",
        "CHK-REGBLOCK-PARTIAL-HOLD",
        "CHK-REGBLOCK-W1C-HOLD",
        "CHK-REGBLOCK-ZERO-WRITE",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_regblock_partial_write_test_seq("smc_regblock_partial_write_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.held == NUM_I2C_CTRL + 1, f"{seq.held} partial-write holds checked"
        assert seq.w1c_held == 2, f"{seq.w1c_held} W1C holds checked"
        assert seq.zero_writes == 3, f"{seq.zero_writes} zero writes checked"
        assert seq.documented == 4, f"{seq.documented} documented-effect accesses checked"
