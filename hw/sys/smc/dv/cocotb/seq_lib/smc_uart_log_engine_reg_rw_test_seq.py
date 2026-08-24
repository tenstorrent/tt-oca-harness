# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART/log-engine register RW depth test over real SEP_IN AXI."""

from __future__ import annotations

from .smc_addr_map import smc_bootrom_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_UART0 = 0  # UART_LOG_ENGINE_WRAP idx

UART_LOG_READS = [
    ("UART_LOG_ENGINE_CTRL", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
        _UART0), None),
    ("UART0_IIR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", _UART0), None),
    ("UART0_LSR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", _UART0), None),
    ("UART0_MSR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", _UART0), None),
    ("UART0_SCR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", _UART0), None),
    ("LOG_ENGINE_CTRL", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR",
        _UART0), None),
    ("LOG_ENGINE_REGION_SIZE", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR",
        _UART0), None),
    ("LOG_ENGINE_REGION_ADDR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR",
        _UART0), None),
    ("LOG_ENGINE_INTR_ENABLE", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR",
        _UART0), None),
    ("LOG_ENGINE_LOG_CTRL_0", smc_bootrom_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_LOG_CTRL_0__BASE_ADDR"),
     None),
]

# LOG_ENGINE_LOG_CTRL_0 is intentionally READ-only-swept (see UART_LOG_READS)
# and NOT part of the write/restore sweep (arbiter assume on unfinished log write).
UART_LOG_WRITES = [
    ("UART_LOG_ENGINE_CTRL", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
        _UART0), 0x1, 0x1),
    ("UART0_SCR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", _UART0),
     0x5A, 0xFF),
    ("LOG_ENGINE_REGION_SIZE", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR",
        _UART0), 0x0000_1000, 0x000F_FFFF),
    ("LOG_ENGINE_REGION_ADDR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR",
        _UART0), 0x0000_2000, 0xFFFF_FFFF),
    ("LOG_ENGINE_INTR_ENABLE", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR",
        _UART0), 0x0000_0011, 0x0000_0011),
]


class smc_uart_log_engine_reg_rw_test_seq(SmcCsrSeq):
    """Port the low-risk legacy UART/log-engine register RW coverage."""

    def __init__(self, name: str = "smc_uart_log_engine_reg_rw_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(UART_LOG_READS)

        original = []
        for name, addr, pattern, mask in UART_LOG_WRITES:
            old_value = await self.csr_read(f"{name}_SAVE", addr)
            original.append((name, addr, old_value, mask))
            await self.csr_write(name, addr, pattern)
            got = await self.csr_read(f"{name}_READBACK", addr)
            assert (got & mask) == (pattern & mask), (
                f"{name} readback 0x{got:x} does not match 0x{pattern:x} mask 0x{mask:x}"
            )

        for name, addr, value, mask in reversed(original):
            await self.csr_write(f"{name}_RESTORE", addr, value)
            got = await self.csr_read(f"{name}_RESTORE_READBACK", addr)
            assert (got & mask) == (value & mask), (
                f"{name} restore got 0x{got:x}, expected 0x{value:x} mask 0x{mask:x}"
            )

        expected_accesses = len(UART_LOG_READS) + (len(UART_LOG_WRITES) * 5)
        assert self.accesses == expected_accesses, "UART/log-engine RW depth mismatch"
