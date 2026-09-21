# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C multi-instance CSR precheck (TC_SMC_P1CG_02).

RTL exposes 3 controllers (I2C_0/1/2)
plus a top-level I2C_CTRL block. Sweeps a compact set of representative
CSR reads at each instance base to prove per-instance address decode +
reset defaults.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Instance base = PeakRDL I2C INTR_STATE / I2C_CTRL_REGS; all fields reset 0x0.
I2C_INSTANCE_READS = [
    ("I2C_1_BASE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1), 0x0),
    ("I2C_2_BASE", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 2), 0x0),
    ("I2C_CTRL", smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0), 0x0),
]


class smc_i2c_multi_instance_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        for name, addr, expected in I2C_INSTANCE_READS:
            await self.csr_read(name, addr, expected=expected)
        self.assert_all_reachable(len(I2C_INSTANCE_READS), "I2C_MULTI_INSTANCE")
        value_checks = sb.sys_axi_value_checks_seen - value_checks_before
        assert value_checks == len(I2C_INSTANCE_READS), (
            f"I2C_MULTI_INSTANCE: the scoreboard booked {value_checks} exact-value compares "
            f"for {len(I2C_INSTANCE_READS)} reads that each carry an expected word"
        )
        cocotb.log.info(
            "CHK-I2C-INSTANCE-RESET-DECODE: %d I2C instance base reads (%s) each returned "
            "OKAY and matched its reset word in a scoreboard value compare; %d value "
            "compares booked",
            len(I2C_INSTANCE_READS),
            ", ".join(f"{name}@0x{addr:08x}=0x{exp:x}" for name, addr, exp in I2C_INSTANCE_READS),
            value_checks,
        )
