# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The four I2C FIFO resets, pulsed against a measured fill level.

On all three instances with the block idle: fill the controller transmit FIFO
through FDATA and the target transmit FIFO through TXDATA to two different
depths, measure both levels, then pulse each of the four FIFO_CTRL resets and
check what moved. FMTRST and TXRST must empty the FIFO the RDL names for them;
RXRST and ACQRST, whose FIFOs software cannot fill, must leave both measured
levels exactly where they are.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_fifo_reset_pulse_test_seq import smc_i2c_fifo_reset_pulse_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 3 I2C instances, 25 SEP_IN AXI accesses each:
#   the two baseline status reads                                             2
#   three FDATA writes and five TXDATA writes                                 8
#   the two status reads that measure the fill                                2
#   four reset pulses, each with both status registers read after it         12
#   the FIFO_CTRL readback                                                     1
I2C_FIFO_RESET_PULSE_MIN_CSR_ACCESSES = 3 * 25


@pyuvm.test()
class smc_i2c_fifo_reset_pulse_test(smc_base_test):
    """Pulse each I2C FIFO reset against a measured fill level."""

    required_evidence = (
        "CHK-I2C-FIFO-RST-EMPTIES",
        "CHK-I2C-FIFO-RST-ONE-HOT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_fifo_reset_pulse_test_seq("smc_i2c_fifo_reset_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            min_csr_accesses=I2C_FIFO_RESET_PULSE_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.instances} I2C instances, {seq.emptied} FIFOs emptied by their "
                f"reset, {seq.undisturbed} resets shown not to disturb another FIFO"
            ),
        )
