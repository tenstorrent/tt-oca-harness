# SPDX-License-Identifier: Apache-2.0
"""UART/log-engine register RW depth test over real SEP_IN AXI."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

UART_LOG_READS = [
    ("UART_LOG_ENGINE_CTRL", 0xC000_A000, None),
    ("UART0_IIR", 0xC000_A108, None),
    ("UART0_LSR", 0xC000_A114, None),
    ("UART0_MSR", 0xC000_A118, None),
    ("UART0_SCR", 0xC000_A11C, None),
    ("LOG_ENGINE_CTRL", 0xC000_A200, None),
    ("LOG_ENGINE_REGION_SIZE", 0xC000_A204, None),
    ("LOG_ENGINE_REGION_ADDR", 0xC000_A208, None),
    ("LOG_ENGINE_INTR_ENABLE", 0xC000_A218, None),
    ("LOG_ENGINE_LOG_CTRL_0", 0xC000_A240, None),
]

# LOG_ENGINE_LOG_CTRL_0 (0xC000_A240) is intentionally READ-only-swept (see
# UART_LOG_READS) and NOT part of the write/restore sweep. Its LOG_LEN field is a
# trigger, not a plain RW register: writing a nonzero length asserts a
# prim_arbiter_tree request (log_engine.sv: log_reqs[i] = log_lens[i] != 0) that
# the RTL clears in hardware only when the log write completes
# (LOG_CTRL.LOG_LEN.hwclr = log_write_done). The DUT-only OSS bench does not
# service the log-engine write path, so the write never completes; a software
# restore-to-0 would then drop an ungranted request and trip the arbiter's
# ReqStaysHighUntilGranted0_M assume (req_chk_i is tied high in log_engine.sv).
# Write/restore-sweeping it is therefore unsafe in this proxy bench.
UART_LOG_WRITES = [
    ("UART_LOG_ENGINE_CTRL", 0xC000_A000, 0x1, 0x1),
    ("UART0_SCR", 0xC000_A11C, 0x5A, 0xFF),
    ("LOG_ENGINE_REGION_SIZE", 0xC000_A204, 0x0000_1000, 0x000F_FFFF),
    ("LOG_ENGINE_REGION_ADDR", 0xC000_A208, 0x0000_2000, 0xFFFF_FFFF),
    ("LOG_ENGINE_INTR_ENABLE", 0xC000_A218, 0x0000_0011, 0x0000_0011),
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
