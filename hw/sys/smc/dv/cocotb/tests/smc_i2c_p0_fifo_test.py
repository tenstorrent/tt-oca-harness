# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0/I2C1 FMT/TX/RX/ACQ threshold interrupts."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_fifo_test_seq import smc_i2c_p0_fifo_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_fifo_test(smc_base_test):
    """ACQ / TX FIFO threshold interrupt proof."""

    required_evidence = (
        "CHK-I2C-P0-FIFO",
        "CHK-I2C-P0-FIFO-ACQ",
        "CHK-I2C-P0-FIFO-TX",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_fifo_test_seq("i2c_p0_fifo_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.acq_ok and seq.tx_ok, f"fifo incomplete acq={seq.acq_ok} tx={seq.tx_ok}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the ACQ/TX threshold IRQ polls are timing-dependent.
            min_csr_accesses=36,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"ACQ+TX threshold IRQs acq={seq.acq_ok} tx={seq.tx_ok}",
        )
