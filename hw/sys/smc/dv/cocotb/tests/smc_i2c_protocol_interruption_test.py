# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C transactions cut short at every phase, on all three instances."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_protocol_interruption_test_seq import (
    smc_i2c_protocol_interruption_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_protocol_interruption_test(smc_base_test):
    """Interrupt I2C transactions at every phase and prove each instance recovers."""

    required_evidence = (
        "CHK-I2C0-INTR-ADDR-PHASE",
        "CHK-I2C0-INTR-DATA-PHASE",
        "CHK-I2C0-INTR-HOST-DISABLE",
        "CHK-I2C0-INTR-TARGET-DISABLE",
        "CHK-I2C1-INTR-ADDR-PHASE",
        "CHK-I2C1-INTR-DATA-PHASE",
        "CHK-I2C1-INTR-TARGET-DISABLE",
        "CHK-I2C2-INTR-ADDR-PHASE",
        "CHK-I2C2-INTR-DATA-PHASE",
        "CHK-I2C2-INTR-TARGET-DISABLE",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_protocol_interruption_test_seq("smc_i2c_protocol_interruption_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, the
            # bring-up and FIFO resets around every sweep and recovery, and the
            # acquisition drains after each. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=400,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C transactions interrupted at every phase on all three instances",
        )
