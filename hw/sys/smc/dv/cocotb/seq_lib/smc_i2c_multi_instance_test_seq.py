# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: I2C multi-instance CSR precheck (TC_SMC_P1CG_02).

Existing tests only touch I2C_0. RTL exposes 3 controllers (I2C_0/1/2)
plus a top-level I2C_CTRL block. Sweeps a compact set of representative
CSR reads at each instance base to prove per-instance address decode +
reset defaults.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Instance base = i2c.rdl INTR_STATE (0xC000_9200) / i2c_ctrl.rdl (0xC000_9E00);
# all fields reset 0x0 per RDL -> composite reset 0x0 (RDL-traceable, G3
# spec-anchored; identical on Verilator and VCS). Asserting it verifies
# per-instance decode AND spec-defined reset content, not merely an OKAY reply.
I2C_INSTANCE_READS = [
    ("I2C_1_BASE",  0xC000_9200, 0x0),
    ("I2C_2_BASE",  0xC000_9400, 0x0),
    ("I2C_CTRL",    0xC000_9E00, 0x0),
]


class smc_i2c_multi_instance_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for name, addr, expected in I2C_INSTANCE_READS:
            await self.csr_read(name, addr, expected=expected)
        assert self.accesses == len(I2C_INSTANCE_READS), (
            "I2C multi-instance precheck count mismatch"
        )
