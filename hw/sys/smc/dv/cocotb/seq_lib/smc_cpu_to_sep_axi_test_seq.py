# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU-control to SEP-facing CSR reachability precheck."""

from __future__ import annotations

import sys
from pathlib import Path

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_DEFAULT,
    CPU_CTRL_RESET_CTRL_REG_DEFAULT,
    CPU_CTRL_RESET_VECTOR_REG_DEFAULT,
    CPU_CTRL_TEST_CTRL_REG_DEFAULT,
    CPU_CTRL_WDT_TIMEOUT_REG_DEFAULT,
    SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_ADDR,
    SMC_CPU_CTRL_RESET_CTRL_REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
    SMC_CPU_CTRL_TEST_CTRL_REG_ADDR,
    SMC_CPU_CTRL_WDT_TIMEOUT_REG_ADDR,
)

# Spec-anchored reset constants (lower 32b; AxSIZE length=4). Each read verifies
# SMC_CPU_CTRL decode at 0xC0039000+ AND RDL reset content — not merely OKAY.
# (Earlier revision used stale 0xC001_xxxx BASE_CONFIG literals under CPU_CTRL names.)
CPU_CTRL_READS = [
    ("RESET_VECTOR_0", SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
     CPU_CTRL_RESET_VECTOR_REG_DEFAULT & 0xFFFF_FFFF),
    ("RESET_CTRL", SMC_CPU_CTRL_RESET_CTRL_REG_ADDR,
     CPU_CTRL_RESET_CTRL_REG_DEFAULT & 0xFFFF_FFFF),
    ("CORE_RESET_PULSE_COUNT", SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_ADDR,
     CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_DEFAULT & 0xFFFF_FFFF),
    ("WDT_TIMEOUT", SMC_CPU_CTRL_WDT_TIMEOUT_REG_ADDR,
     CPU_CTRL_WDT_TIMEOUT_REG_DEFAULT & 0xFFFF_FFFF),
    ("TEST_CTRL", SMC_CPU_CTRL_TEST_CTRL_REG_ADDR,
     CPU_CTRL_TEST_CTRL_REG_DEFAULT & 0xFFFF_FFFF),
]
CPU_CTRL_SCRATCH_0 = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
CPU_PATTERN = 0xC511_0001


class smc_cpu_to_sep_axi_test_seq(SmcCsrSeq):
    """Precheck CPU-control CSR path until a CPU/firmware source is available."""

    def __init__(self, name: str = "smc_cpu_to_sep_axi_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(CPU_CTRL_READS)
        await self.csr_write_readback("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0,
                                      CPU_PATTERN)
        await self.csr_restore("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0)
        # Closing gate is DUT-sensitive: every read above carried an independent
        # RDL reset expectation via the scoreboard, and scratch write/readback
        # checked the programmed pattern. Do not assert on self.accesses alone.
