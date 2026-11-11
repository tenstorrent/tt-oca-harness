# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 FIFO integrity faults: a real parity fault and a real pointer fault.

`hw/ip/i2c/doc/index.adoc` states that `i2c_fifo_intg_err_o` reports a
hardened-pointer mismatch or a head-entry parity mismatch independent of
`INTR_ENABLE`, that the pointer error holds until the FIFO is cleared and the
parity error clears once the entry is read, and that the SMC ORs the
instances into `smc_ras_o.i2c_intg_err`; `i2c.rdl` states that the
`INTR_STATE.*_FIFO_ERROR` fields report either fault and stay set across a
write of `1` while the error persists (this leaf grades
`CONTROLLER_TX_FIFO_ERROR`). Every other leaf reaches the
`*_FIFO_ERROR` bits through `INTR_TEST`; this one flips a stored bit.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_fifo_integrity_fault_test_seq import smc_i2c_fifo_integrity_fault_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_fifo_integrity_fault_test(smc_base_test):
    """A flipped parity bit or pointer copy must reach the status bit, the output and RAS."""

    required_evidence = ("CHK-I2C-FIFO-INTG-REAL", "CHK-I2C-FIFO-INTG-STATUS")
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_fifo_integrity_fault_test_seq("i2c_fifo_integrity_fault_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the measured values, not on the sequence having run.
        assert seq.ras_with_enable_clear == 1, "the parity fault did not reach the RAS bit"
        assert seq.irq_with_enable_clear == 0, "tb_i2c_irq[0] rose with INTR_ENABLE clear"
        assert seq.irq_with_enable_set == 1, "tb_i2c_irq[0] stayed low with the source enabled"
        assert seq.ras_after_pop == 0, "the RAS bit stayed high after the faulted entry popped"
        assert seq.ras_pointer_fault == 1, "the pointer-copy fault did not reach the RAS bit"
        assert seq.ras_after_fmtrst == 0, "the RAS bit stayed high after FIFO_CTRL.FMTRST"
        assert seq.status_w1c_parity_live == 1, (
            "a W1C cleared the status bit with the parity fault live"
        )
        assert seq.status_pointer_fault == 1, "the pointer-copy fault did not reach the status bit"
        assert seq.status_w1c_pointer_live == 1, (
            "a W1C cleared the status bit with the pointer fault live"
        )
