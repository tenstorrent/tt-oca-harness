# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C multi-instance CSR precheck (TC_SMC_P1CG_02).

The generated map declares three controllers (I2C_0/1/2) plus a top-level
I2C_CTRL block. Two legs, both scoreboard-compared:

* reset content -- the I2C_1 and I2C_2 INTR_STATE bases and the I2C_CTRL base
  read their generated reset word;
* per-instance decode -- every controller's TARGET_ID (plain rw storage,
  i2c.rdl "Target ID Register", reset 0) holds a distinct address pattern while
  the other two hold theirs, and each reads back its own before being
  restored. A stride that aliases two instances, or an undecoded window that
  answers OKAY with zeros, fails the readback; the reset reads alone cannot
  tell those apart, since the reset word is zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import _REPO, reg_field_encode, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_I2C_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    I2C_CTRL_I2C_CTRL_REG_DEFAULT,
    I2C_INTR_STATE_REG_DEFAULT,
    I2C_TARGET_ID_REG_DEFAULT,
)

# Instance base = PeakRDL I2C INTR_STATE / I2C_CTRL_REGS, each with its generated reset.
I2C_INSTANCE_READS = [
    (
        "I2C_1_BASE",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 1),
        I2C_INTR_STATE_REG_DEFAULT,
    ),
    (
        "I2C_2_BASE",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 2),
        I2C_INTR_STATE_REG_DEFAULT,
    ),
    (
        "I2C_CTRL",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0),
        I2C_CTRL_I2C_CTRL_REG_DEFAULT,
    ),
]
I2C_NUM = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_NUM")
I2C_TARGET_ID_RESET = I2C_TARGET_ID_REG_DEFAULT


def _target_id_addr(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", idx)


def _target_id_pattern(idx: int) -> int:
    """Distinct 7-bit target address per controller, packed from the generated layout."""
    return reg_field_encode(_I2C_H, "I2C", "TARGET_ID", address0=0x21 + idx, mask0=0x7F)


I2C_CORESIDENT = [
    (f"I2C_{idx}_TARGET_ID", _target_id_addr(idx), _target_id_pattern(idx), I2C_TARGET_ID_RESET)
    for idx in range(I2C_NUM)
]
# 3 reset reads + I2C_NUM x (pattern write, pattern read, restore write, restore read).
EXPECTED_ACCESSES = len(I2C_INSTANCE_READS) + 4 * I2C_NUM
EXPECTED_VALUE_CHECKS = len(I2C_INSTANCE_READS) + 2 * I2C_NUM


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
        await self.rw_coresident(I2C_CORESIDENT)
        value_checks = sb.sys_axi_value_checks_seen - value_checks_before
        assert value_checks == EXPECTED_VALUE_CHECKS, (
            f"I2C_MULTI_INSTANCE: the scoreboard booked {value_checks} exact-value compares, "
            f"expected {EXPECTED_VALUE_CHECKS}"
        )
        assert self.accesses == EXPECTED_ACCESSES, (
            f"I2C_MULTI_INSTANCE: {self.accesses} accesses issued, expected {EXPECTED_ACCESSES}"
        )
        cocotb.log.info(
            "CHK-I2C-INSTANCE-CORESIDENT: TARGET_ID of I2C_0..%d (%s) each held its own "
            "pattern while the other two held theirs, read it back exactly, then read back "
            "the reset 0x%x after the restore write; %d scoreboard value compares over %d "
            "accesses",
            I2C_NUM - 1,
            ", ".join(f"0x{addr:08x}=0x{pat:08x}" for _n, addr, pat, _r in I2C_CORESIDENT),
            I2C_TARGET_ID_RESET,
            value_checks,
            self.accesses,
        )
