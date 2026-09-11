# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The UART 16550 runs on clk_periph_i: its bit time is 16 x (DIVISOR + 1) peripheral clocks.

``clk_rst.adoc`` (The Peripheral Clock Domain) lists the UART 16550 among the
controllers that "operate within this clock domain" and notes that the
peripheral register crossbar runs on the SMC clock with a CDC bridge into the
peripheral clock downstream. The 16550 baud generator divides its clock by
16 x (DIVISOR + 1) per bit, so a frame of all-zero data bits keeps TX low for
exactly nine bit times (start plus eight data bits) before the stop bit. That
low pulse is timestamped on ``tb_uart0_tx_from_dut`` at simulation-time
resolution and compared with nine bit times of the run's ``clk_periph_i``
period; on every seed the SMC clock period differs from the peripheral one,
so a transmitter clocked from ``clk_smc_i`` produces a pulse outside the
tolerance.

Only the UART cell of the peripheral-clock scenario is closed here. AVSBus,
I2C and I3C timing needs their bus protocols in flight; the PLL wrapper is a
behavioural model in this bench (no reference-clock consumer to observe) and
``rst_telemetry_ni`` is tied to the cold reset in ``tb_top``, so those cells
are named and left open.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, with_timeout
from cocotb.utils import get_sim_time

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

try:
    from cocotb.result import SimTimeoutError
except ImportError:  # cocotb 2.x
    from cocotb.triggers import SimTimeoutError

UART0_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)
UART0_THR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0)
UART0_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART0_LCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0)

UART_EN = 0x1
LCR_DLAB = 0x80
LCR_8N1 = 0x03
UART_DIVISOR = 0x000F
UART_TX_BYTE = 0x00
# 16550: 16 baud-generator ticks per bit, generator divides by DIVISOR + 1.
TICKS_PER_BIT = 16
# Start bit plus eight zero data bits.
LOW_BITS = 9
# The transmitter may start the frame up to one bit time after THR is written.
START_BOUND_BIT_TIMES = 3
# Allowance on the measured pulse: the frame starts and ends on baud ticks,
# each one peripheral clock wide, plus the pad path's sampling.
TOLERANCE_PERIPH_CLOCKS = 2

EXPECTED_ACCESSES = 9


class smc_clock_domain_connectivity_test_seq(SmcCsrSeq):
    """Time the UART0 all-zero frame against the peripheral clock period."""

    def __init__(self, name: str = "smc_clock_domain_connectivity_test_seq") -> None:
        super().__init__(name)
        self.low_ps: int | None = None
        self.expected_ps: int | None = None
        self.smc_alias_ps: int | None = None
        self.tolerance_ps: int | None = None

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        periph_ps = self.cfg.periph_clk_period_ns * 1000
        smc_ps = self.cfg.smc_clk_period_ns * 1000
        assert periph_ps != smc_ps, "the run's clock periods must differ for the domain compare"
        bit_ps = TICKS_PER_BIT * (UART_DIVISOR + 1) * periph_ps
        self.expected_ps = LOW_BITS * bit_ps
        self.smc_alias_ps = LOW_BITS * TICKS_PER_BIT * (UART_DIVISOR + 1) * smc_ps
        self.tolerance_ps = TOLERANCE_PERIPH_CLOCKS * periph_ps
        assert abs(self.smc_alias_ps - self.expected_ps) > self.tolerance_ps

        cg = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART0_EN", UART0_CTRL, UART_EN)
        await self.csr_write("UART0_LCR_DLAB", UART0_LCR, LCR_8N1 | LCR_DLAB)
        await self.csr_write("UART0_DLL", UART0_THR, UART_DIVISOR & 0xFF)
        await self.csr_write("UART0_DLM", UART0_IER, (UART_DIVISOR >> 8) & 0xFF)
        await self.csr_write("UART0_LCR_8N1", UART0_LCR, LCR_8N1)
        await ClockCycles(dut.clk_smc_i, max(64, UART_DIVISOR * 16))
        assert int(dut.tb_uart0_tx_from_dut.value) == 1, "UART0 TX is not idle-high before THR"

        await self.csr_write("UART0_THR", UART0_THR, UART_TX_BYTE)
        start_bound_ns = START_BOUND_BIT_TIMES * bit_ps // 1000
        try:
            await with_timeout(FallingEdge(dut.tb_uart0_tx_from_dut), start_bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"UART0 TX never started the frame within {start_bound_ns} ns of THR"
            ) from exc
        t_low = int(round(get_sim_time("ps")))
        pulse_bound_ns = (self.expected_ps * 2) // 1000
        try:
            await with_timeout(RisingEdge(dut.tb_uart0_tx_from_dut), pulse_bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"UART0 TX stayed low for more than {pulse_bound_ns} ns after the start bit"
            ) from exc
        self.low_ps = int(round(get_sim_time("ps"))) - t_low

        assert abs(self.low_ps - self.expected_ps) <= self.tolerance_ps, (
            f"UART0 TX low pulse {self.low_ps} ps is not {LOW_BITS} x {TICKS_PER_BIT} x "
            f"({UART_DIVISOR} + 1) clk_periph_i periods = {self.expected_ps} ps "
            f"(tolerance {self.tolerance_ps} ps; the same frame on clk_smc_i would be "
            f"{self.smc_alias_ps} ps)"
        )
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        self.assert_all_reachable(EXPECTED_ACCESSES, "CLOCK_DOMAIN_CONNECTIVITY")
        cocotb.log.info(
            "CHK-UART-ON-CLK-PERIPH: UART0 all-zero frame held TX low for %d ps == %d x %d x "
            "(0x%x + 1) x clk_periph_i %d ps = %d ps (tolerance %d ps); on clk_smc_i (%d ps) the "
            "same frame would be %d ps",
            self.low_ps,
            LOW_BITS,
            TICKS_PER_BIT,
            UART_DIVISOR,
            periph_ps,
            self.expected_ps,
            self.tolerance_ps,
            smc_ps,
            self.smc_alias_ps,
        )
        cocotb.log.info(
            "CHK-CLOCK-DOMAIN-NOT-CLOSED: avsbus-on-clk-periph, i2c-on-clk-periph, "
            "i3c-on-clk-periph (bus protocol not driven here); clk-ref-reaches-pll-wrapper (PLL "
            "wrapper is a behavioural model in this bench); telemetry-reset-asserted/released "
            "(rst_telemetry_ni tied to the cold reset in tb_top)"
        )
