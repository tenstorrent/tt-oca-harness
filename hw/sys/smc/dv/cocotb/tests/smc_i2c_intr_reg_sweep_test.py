# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C interrupt and event register cycles on all three instances.

Drives INTR_ENABLE and INTR_TEST to all-ones and all-zeros through
half-register writes, raises and clears the INTR_STATE events the write-only
INTR_TEST fields map to, writes the whole declared mask of CONTROLLER_EVENTS
and TARGET_EVENTS twice, and reads the two tail registers of the read mux
against their RDL reset.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_intr_reg_sweep_test_seq import smc_i2c_intr_reg_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 3 I2C instances, 42 SEP_IN AXI accesses each:
#   INTR_ENABLE and INTR_TEST cycles: reset read, 2x(half write + readback) for
#     the ones pattern, the same for the zeros pattern, 2 restore writes,
#     restore read -- 12 each                                                24
#   INTR_TEST pulse leg: the clear-state read, the test write, the raised read,
#     the clearing write and the cleared read                                 5
#   CONTROLLER_EVENTS and TARGET_EVENTS legs: the clear-state read, the
#     full-width write and its readback, the half-register write and its
#     readback -- 5 each                                                     10
#   read-mux tail: the STATUS read plus the two tail register reads            3
I2C_INTR_REG_SWEEP_MIN_CSR_ACCESSES = 3 * 42


@pyuvm.test()
class smc_i2c_intr_reg_sweep_test(smc_base_test):
    """Cycle the I2C interrupt and event registers on every instance."""

    required_evidence = (
        "CHK-I2C-EVENTS-W1C",
        "CHK-I2C-INTR-REG-SWEEP",
        "CHK-I2C-INTR-TEST-STATE",
        "CHK-I2C-READMUX-TAIL",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_intr_reg_sweep_test_seq("smc_i2c_intr_reg_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            min_csr_accesses=I2C_INTR_REG_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} I2C register cycles, {seq.pulses} INTR_TEST pulses, "
                f"{seq.event_legs} event legs, {seq.tail_reads} tail reads"
            ),
        )
