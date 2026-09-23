# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C configuration register cycles on all three instances, block idle.

Drives the control register, the five timing registers, both FIFO threshold
registers, the three timeout controls, the NACK handler timeout, the target
identity, the bus override and the SMBus control to all-ones and all-zeros
through half-register writes, and restores each to its RDL reset.
CTRL.ENABLEHOST and CTRL.ENABLETARGET are held at their reset so neither engine
starts, and every word the sweep would leave resident is checked against that
and against the override's line sense before any access goes out.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_config_regblock_sweep_test_seq import smc_i2c_config_regblock_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 3 I2C instances, 15 configuration registers each, and one half-register cycle
# per register: the reset read, 2x(half write + readback) for the ones pattern,
# the same for the zeros pattern, the 2 restore writes and the restore read --
# 12 accesses per cycle.
I2C_CONFIG_REG_SWEEP_MIN_CSR_ACCESSES = 3 * 15 * 12


@pyuvm.test()
class smc_i2c_config_regblock_sweep_test(smc_base_test):
    """Cycle the I2C configuration registers on every instance, block idle."""

    required_evidence = (
        "CHK-I2C-CONFIG-IDLE-GUARD",
        "CHK-I2C-CONFIG-REG-SWEEP",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_config_regblock_sweep_test_seq("smc_i2c_config_regblock_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            min_csr_accesses=I2C_CONFIG_REG_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.instances} I2C instances, {seq.registers_swept} register cycles, "
                f"{seq.registers_checked} guarded before any access"
            ),
        )
