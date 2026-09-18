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

# Spec-anchored reset constants. Each read verifies SMC_CPU_CTRL decode at
# 0xC0039000+ AND full RDL reset content — not merely OKAY. The addresses are
# CPU_CTRL's own, not BASE_CONFIG's.
#
# The access width is per-register: CORE_RESET_PULSE_COUNT.core_resets_done has
# RDL reset 0xF at bits [35:32], is declared ``regwidth = 64; accesswidth = 64``
# (cpu_ctrl.rdl:89-91) and sits 8-byte aligned (0x28), so it is read as one
# AxSIZE=8 beat and never masked to [31:0] ([EXACT-EXPECTATION]). The other four
# defaults are zero above bit 31, so their AxSIZE stays 4.
CPU_CTRL_READS = [
    ("RESET_VECTOR_0", SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR, CPU_CTRL_RESET_VECTOR_REG_DEFAULT, 4),
    ("RESET_CTRL", SMC_CPU_CTRL_RESET_CTRL_REG_ADDR, CPU_CTRL_RESET_CTRL_REG_DEFAULT, 4),
    # length=8: carries core_resets_done[35:32] == 0xF into the compare.
    (
        "CORE_RESET_PULSE_COUNT",
        SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_ADDR,
        CPU_CTRL_CORE_RESET_PULSE_COUNT_REG_DEFAULT,
        8,
    ),
    ("WDT_TIMEOUT", SMC_CPU_CTRL_WDT_TIMEOUT_REG_ADDR, CPU_CTRL_WDT_TIMEOUT_REG_DEFAULT, 4),
    ("TEST_CTRL", SMC_CPU_CTRL_TEST_CTRL_REG_ADDR, CPU_CTRL_TEST_CTRL_REG_DEFAULT, 4),
]
CPU_CTRL_SCRATCH_0 = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
CPU_PATTERN = 0xC511_0001


class smc_cpu_to_sep_axi_test_seq(SmcCsrSeq):
    """Read the CPU_CTRL reset defaults and write/readback SCRATCH_0 over SEP_IN."""

    def __init__(self, name: str = "smc_cpu_to_sep_axi_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        # Explicit loop rather than csr_read_many(): the table carries a
        # per-register access length (see CPU_CTRL_READS) and csr_read_many only
        # issues the default 4-byte reads.
        for name, addr, expected, length in CPU_CTRL_READS:
            await self.csr_read(name, addr, expected=expected, length=length)
        await self.csr_write_readback("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0, CPU_PATTERN)
        await self.csr_restore("CPU_CTRL_SCRATCH_0", CPU_CTRL_SCRATCH_0)
        # Closing gate is DUT-sensitive: every read above carried an independent
        # RDL reset expectation via the scoreboard, and scratch write/readback
        # checked the programmed pattern. Do not assert on self.accesses alone.
