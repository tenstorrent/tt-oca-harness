# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two unrelated interrupt sources asserted at once, then both released.

The software sync interrupt (``SYNC_REG.sync``, ``reset_unit.rdl``) and the
UART0 transmitter-holding interrupt (``IER.ETBEI`` with ``ITR.TTBEI``, the
16550 interrupt test register) come from different blocks on different clock
domains and reach separate wrapper outputs. The sequence raises the sync source
and holds it while it raises the UART source, requires both outputs at 1 in
the same ``clk_smc_i`` sample, releases the UART source and requires the sync
output still 1, then releases the sync source and requires both at 0. A shared
or cross-wired output fails one of those samples. The UART clock gate and both
registers are restored.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_probe_positive_control import (
    IER_ETBEI,
    ITR_TTBEI,
    SYNC_REG,
    SYNC_REG_SYNC_BM,
    SYNC_REG_SYNC_RESET,
    UART0_CTRL,
    UART0_IER,
    UART0_ITR,
    UART_EN,
)

# clk_smc_i cycles within which an output must reach a level after the CSR
# write that sets it has completed, and cycles it must then hold that level.
LEVEL_BOUND_CYCLES = 128
LEVEL_HOLD_CYCLES = 4


def _outputs() -> tuple[int, int]:
    dut = cocotb.top
    sync, uart = dut.tb_sync_irq.value, dut.tb_uart_irq_any.value
    assert sync.is_resolvable and uart.is_resolvable, (
        f"tb_sync_irq={sync} tb_uart_irq_any={uart} is X/Z"
    )
    return int(sync), int(uart)


async def _await_outputs(want: tuple[int, int], label: str) -> int:
    """Poll every clk_smc_i cycle until both outputs read ``want``, then hold-verify."""
    clk = cocotb.top.clk_smc_i
    last = None
    for cycle in range(1, LEVEL_BOUND_CYCLES + 1):
        await ClockCycles(clk, 1)
        last = _outputs()
        if last == want:
            for _ in range(LEVEL_HOLD_CYCLES):
                await ClockCycles(clk, 1)
                held = _outputs()
                assert held == want, (
                    f"{label}: (sync, uart) reached {want} and then read {held} within "
                    f"{LEVEL_HOLD_CYCLES} cycles"
                )
            return cycle
    raise AssertionError(
        f"{label}: (tb_sync_irq, tb_uart_irq_any) never read {want} within "
        f"{LEVEL_BOUND_CYCLES} clk_smc_i cycles; last {last}"
    )


class smc_irq_concurrent_seq(SmcCsrSeq):
    """Sync and UART0 interrupt outputs asserted together and released one at a time."""

    def __init__(self, name: str = "smc_irq_concurrent_seq") -> None:
        super().__init__(name)
        self.cycles: dict[str, int] = {}

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        assert _outputs() == (0, 0), (
            f"(tb_sync_irq, tb_uart_irq_any) is {_outputs()} before any stimulus"
        )
        cg = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART0_EN", UART0_CTRL, UART_EN)

        await self.csr_write("SYNC_REG_SET", SYNC_REG, SYNC_REG_SYNC_BM)
        self.cycles["sync_only"] = await _await_outputs((1, 0), "sync raised")
        await self.csr_write("UART0_IER_ETBEI", UART0_IER, IER_ETBEI)
        await self.csr_write("UART0_ITR_TTBEI", UART0_ITR, ITR_TTBEI)
        self.cycles["both"] = await _await_outputs((1, 1), "sync held, UART raised")

        await self.csr_write("UART0_ITR_CLR", UART0_ITR, 0)
        await self.csr_write("UART0_IER_CLR", UART0_IER, 0)
        self.cycles["uart_released"] = await _await_outputs((1, 0), "UART released")
        await self.csr_write("SYNC_REG_CLR", SYNC_REG, SYNC_REG_SYNC_RESET)
        await self.csr_read("SYNC_REG_CLR_RB", SYNC_REG, expected=SYNC_REG_SYNC_RESET)
        self.cycles["both_released"] = await _await_outputs((0, 0), "both released")
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        cocotb.log.info(
            "CHK-IRQ-CONCURRENT-SOURCES: SYNC_REG.sync raised tb_sync_irq alone after %d "
            "cycle(s); UART0 ETBEI+TTBEI then raised tb_uart_irq_any with tb_sync_irq still 1 "
            "after %d; clearing the UART source dropped only it after %d; clearing SYNC_REG "
            "returned both to 0 after %d (clk_smc_i cycles, each level held %d)",
            self.cycles["sync_only"],
            self.cycles["both"],
            self.cycles["uart_released"],
            self.cycles["both_released"],
            LEVEL_HOLD_CYCLES,
        )
