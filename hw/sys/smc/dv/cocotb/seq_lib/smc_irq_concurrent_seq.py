# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three unrelated interrupt sources asserted together, then released one at a time.

The software sync interrupt (``SYNC_REG.sync``, ``reset_unit.rdl``), the UART0
transmitter-holding interrupt (``IER.ETBEI`` with ``ITR.TTBEI``, the 16550
interrupt test register) and the GPIO0 active-low level interrupt (GPIO0 as an
input with its interrupt enabled, its pad driven from the top-level pad pins)
come from different blocks and reach separate wrapper outputs. The sequence
raises them in turn and requires each output to rise while the earlier ones
stay up, so all three read 1 in one ``clk_smc_i`` sample, then releases them in
reverse order and requires each release to drop only its own output. A shared
or cross-wired output fails one of those samples. The UART clock gate, both
UART registers and GPIO0's DATA_CTRL are restored and the pad drive released.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_probe_positive_control import (
    GPIO0_DATA_CTRL,
    GPIO0_INPUT_ACTIVE_LOW_IRQ,
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

# clk_smc_i cycles within which the outputs must reach a level after the
# stimulus that sets it, and cycles they must then hold that level.
LEVEL_BOUND_CYCLES = 128
LEVEL_HOLD_CYCLES = 4

_PROBES = ("tb_sync_irq", "tb_uart_irq_any", "tb_gpio_irq_any")


def _outputs() -> tuple[int, ...]:
    dut = cocotb.top
    values = [getattr(dut, name).value for name in _PROBES]
    assert all(v.is_resolvable for v in values), (
        f"{dict(zip(_PROBES, map(str, values), strict=True))} has X/Z"
    )
    return tuple(int(v) for v in values)


async def _await_outputs(want: tuple[int, ...], label: str) -> int:
    """Poll every clk_smc_i cycle until the outputs read ``want``, then hold-verify."""
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
                    f"{label}: (sync, uart, gpio) reached {want} and then read {held} within "
                    f"{LEVEL_HOLD_CYCLES} cycles"
                )
            return cycle
    raise AssertionError(
        f"{label}: (tb_sync_irq, tb_uart_irq_any, tb_gpio_irq_any) never read {want} within "
        f"{LEVEL_BOUND_CYCLES} clk_smc_i cycles; last {last}"
    )


class smc_irq_concurrent_seq(SmcCsrSeq):
    """Sync, UART0 and GPIO0 interrupt outputs asserted together and released in turn."""

    def __init__(self, name: str = "smc_irq_concurrent_seq") -> None:
        super().__init__(name)
        self.cycles: dict[str, int] = {}

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert _outputs() == (0, 0, 0), f"interrupt outputs are {_outputs()} before any stimulus"
        cg = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        gpio_saved = await self.csr_read("GPIO0_DATA_CTRL_SAVE", GPIO0_DATA_CTRL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART0_EN", UART0_CTRL, UART_EN)
        dut.tb_gpio_ext_drive_en.value = 0x1
        dut.tb_gpio_ext_drive_value.value = 0x1
        await self.csr_write(
            "GPIO0_INPUT_ACTIVE_LOW_IRQ", GPIO0_DATA_CTRL, GPIO0_INPUT_ACTIVE_LOW_IRQ
        )
        await _await_outputs((0, 0, 0), "GPIO0 armed with its pad high")

        await self.csr_write("SYNC_REG_SET", SYNC_REG, SYNC_REG_SYNC_BM)
        self.cycles["sync"] = await _await_outputs((1, 0, 0), "sync raised")
        await self.csr_write("UART0_IER_ETBEI", UART0_IER, IER_ETBEI)
        await self.csr_write("UART0_ITR_TTBEI", UART0_ITR, ITR_TTBEI)
        self.cycles["uart"] = await _await_outputs((1, 1, 0), "UART raised")
        dut.tb_gpio_ext_drive_value.value = 0x0
        self.cycles["gpio"] = await _await_outputs((1, 1, 1), "GPIO0 raised")

        dut.tb_gpio_ext_drive_value.value = 0x1
        self.cycles["gpio_released"] = await _await_outputs((1, 1, 0), "GPIO0 released")
        await self.csr_write("UART0_ITR_CLR", UART0_ITR, 0)
        await self.csr_write("UART0_IER_CLR", UART0_IER, 0)
        self.cycles["uart_released"] = await _await_outputs((1, 0, 0), "UART released")
        await self.csr_write("SYNC_REG_CLR", SYNC_REG, SYNC_REG_SYNC_RESET)
        await self.csr_read("SYNC_REG_CLR_RB", SYNC_REG, expected=SYNC_REG_SYNC_RESET)
        self.cycles["sync_released"] = await _await_outputs((0, 0, 0), "sync released")

        dut.tb_gpio_ext_drive_en.value = 0x0
        await self.csr_write("GPIO0_DATA_CTRL_RESTORE", GPIO0_DATA_CTRL, gpio_saved)
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)

        cocotb.log.info(
            "CHK-IRQ-CONCURRENT-SOURCES: SYNC_REG.sync, then UART0 ETBEI+TTBEI, then the GPIO0 "
            "pad going low raised tb_sync_irq, tb_uart_irq_any and tb_gpio_irq_any in turn "
            "with the earlier outputs still 1 (after %d, %d, %d cycles), and releasing them in "
            "reverse dropped only each one's own output (after %d, %d, %d cycles; clk_smc_i, "
            "each level held %d)",
            self.cycles["sync"],
            self.cycles["uart"],
            self.cycles["gpio"],
            self.cycles["gpio_released"],
            self.cycles["uart_released"],
            self.cycles["sync_released"],
            LEVEL_HOLD_CYCLES,
        )
