# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 register writes landed on the cycle a transmit or receive event fires.

Two events inside `uart_core.sv` last a single clock, and a register write
that takes effect on that clock does something no other leaf does:

* **The transmit FIFO emptying.** `transmitter_holding_register_empty_intr_cleared`
  is cleared on the cycle the FIFO goes empty and set by a THR write. A THR
  write on that same cycle leaves the FIFO holding a byte with the flag
  clear.
* **The receive timeout.** The timeout count equals its limit for one cycle
  before it restarts. A write clearing `FCR.FIFO_ENABLE` that takes effect on
  that cycle turns the timeout off while the count stands at its limit.

The register path from SEP_IN to the UART crosses into the UART clock, so its
length in UART clocks depends on the run's clock periods. Each run measures
it first: a write setting `LCR.SET_BREAK` drives the TX pad low one clock
after it takes effect, so the clocks from the write's call to the TX pad
falling give the path's length. Both events are then placed from an anchor
the bench controls or sees:

* The FIFO empties when the second of two queued bytes moves to the
  transmitter, 288 clocks after the first byte's start bit reaches the pad
  (divisor 1, 8N1: nine bit times of 32 clocks), so the third byte's write is
  called that many clocks after the pad falls, less the path's length.
* The bench drives a byte on the RX pad from a clock edge it chooses. The
  timeout count reaches its limit of 40 bit ticks 1589 clocks after the
  start bit begins, so the FCR write is called that many clocks after the
  start bit, less the path's length.

Each is swept over two clocks either side of that alignment, since the
crossing adds a clock of jitter. Every sweep point still has to behave as the
registers describe: with the TX pad wired back to the RX pad, all three bytes
of each transmit point have to arrive in order, and after each receive point
a byte received with the FIFO enabled again has to read back intact.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Edge, FallingEdge, ReadOnly, RisingEdge

from .smc_addr_map import UART_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_uart_rbr_error_path_test_seq import (
    CLOCK_GATE_CONTROL,
    FCR_FIFO_ENABLE,
    LCR_DLAB,
    LSR_DR,
    UART_EN,
    WLS_8,
    _uart_reg,
)

UART = 0
#: Divisor 1: one bit is 16 * (1 + 1) UART clocks.
DIVISOR = 1
BIT_CYCLES = 32
LCR_BREAK = 1 << 6
FCR_RESETS = 0x6
#: Clocks from the first byte's start bit on the TX pad to the transmit FIFO
#: going empty as the second byte moves to the transmitter.
EMPTY_AFTER_START = 288
#: Clocks from the start of a bench-driven start bit to the cycle the receive
#: timeout count equals its limit.
TIMEOUT_AFTER_START = 1589
OFFSETS = (-2, -1, 0, 1, 2)
TX_BYTES = (0x11, 0x22, 0x33)
RX_BYTE = 0x3C
CHECK_BYTE = 0xA6
POLL_LIMIT = 400


class smc_uart_window_landing_test_seq(SmcCsrSeq):
    """Land a THR write on the TX-empty cycle and an FCR write on the RX-timeout cycle."""

    def __init__(self, name: str = "smc_uart_window_landing_test_seq") -> None:
        super().__init__(name)
        self.r = {
            "ctrl": smc_indexed_addr(
                "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
                UART,
            ),
            **{k: _uart_reg(k.upper(), UART) for k in ("rbr", "ier", "iir", "lcr", "mcr", "lsr")},
        }
        self.cable_on = False
        self.path = -1

    async def _cable(self) -> None:
        dut = cocotb.top
        while True:
            await Edge(dut.tb_uart0_tx_from_dut)
            if self.cable_on:
                dut.tb_uart0_rx_ext_drive.value = int(dut.tb_uart0_tx_from_dut.value)

    async def _setup(self, tag: str) -> None:
        r = self.r
        await self.csr_write(f"{tag}_EN", r["ctrl"], UART_EN)
        await self.csr_write(f"{tag}_MCR", r["mcr"], 0)
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], WLS_8 | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], DIVISOR)
        await self.csr_write(f"{tag}_DLH", r["ier"], 0)
        await self.csr_write(f"{tag}_LCR", r["lcr"], WLS_8)
        await self.csr_write(f"{tag}_FCR", r["iir"], FCR_FIFO_ENABLE | FCR_RESETS)
        await self.csr_write(f"{tag}_IER", r["ier"], 0)

    async def _edges(self, count: int) -> None:
        for _ in range(count):
            await RisingEdge(cocotb.top.clk_periph_i)

    async def _tx_fall(self) -> int:
        """Clocks until the TX pad reads low, counted from the caller's edge."""
        dut = cocotb.top
        edges = 0
        while True:
            await RisingEdge(dut.clk_periph_i)
            edges += 1
            await ReadOnly()
            if not int(dut.tb_uart0_tx_from_dut.value):
                return edges

    async def _measure_path(self) -> int:
        """Clocks from a register write's call to its effect in the UART."""
        await RisingEdge(cocotb.top.clk_periph_i)
        write = cocotb.start_soon(self.csr_write("PATH_BREAK", self.r["lcr"], WLS_8 | LCR_BREAK))
        # SET_BREAK reaches the pad through one output flop.
        path = await self._tx_fall() - 1
        await write
        await self.csr_write("PATH_BREAK_OFF", self.r["lcr"], WLS_8)
        await ClockCycles(cocotb.top.clk_periph_i, 4 * BIT_CYCLES)
        return path

    async def _read_bytes(self, tag: str, count: int) -> list[int]:
        got: list[int] = []
        for _ in range(POLL_LIMIT):
            if len(got) == count:
                break
            lsr = await self.csr_read(f"{tag}_LSR", self.r["lsr"])
            if lsr & LSR_DR:
                got.append(await self.csr_read(f"{tag}_RBR", self.r["rbr"]) & 0xFF)
            else:
                await ClockCycles(cocotb.top.clk_periph_i, BIT_CYCLES)
        return got

    async def _launch_after(self, edges: int, tag: str, addr: int, value: int) -> None:
        await self._edges(edges)
        await self.csr_write(tag, addr, value)

    async def _empty_leg(self, tag: str, offset: int) -> None:
        dut = cocotb.top
        await self._setup(tag)
        self.cable_on = True
        await RisingEdge(dut.clk_periph_i)
        first = cocotb.start_soon(self.csr_write(f"{tag}_THR0", self.r["rbr"], TX_BYTES[0]))
        await self._tx_fall()
        # The THR write takes effect on the clock after its request, so the
        # request lands on the empty cycle when called one clock later.
        third = cocotb.start_soon(
            self._launch_after(
                EMPTY_AFTER_START - (self.path - 1) + offset,
                f"{tag}_THR2",
                self.r["rbr"],
                TX_BYTES[2],
            )
        )
        await first
        await self.csr_write(f"{tag}_THR1", self.r["rbr"], TX_BYTES[1])
        await third
        got = await self._read_bytes(tag, len(TX_BYTES))
        self.cable_on = False
        assert got == list(TX_BYTES), (
            f"{tag}: the TX pad wired back to RX delivered {[hex(b) for b in got]}, not "
            f"{[hex(b) for b in TX_BYTES]}; a THR write offset {offset} clocks from the FIFO "
            f"emptying lost or reordered a byte"
        )

    async def _drive_rx_byte(self, value: int) -> None:
        dut = cocotb.top
        for bit in [0] + [(value >> i) & 1 for i in range(8)] + [1]:
            dut.tb_uart0_rx_ext_drive.value = bit
            await ClockCycles(dut.clk_periph_i, BIT_CYCLES, rising=False)

    async def _timeout_leg(self, tag: str, offset: int) -> None:
        dut = cocotb.top
        await self._setup(tag)
        await RisingEdge(dut.clk_periph_i)
        await FallingEdge(dut.clk_periph_i)
        writer = cocotb.start_soon(
            self._launch_after(
                TIMEOUT_AFTER_START - self.path + offset, f"{tag}_FCR_OFF", self.r["iir"], 0
            )
        )
        await self._drive_rx_byte(RX_BYTE)
        await writer
        await self.csr_write(f"{tag}_FCR_ON", self.r["iir"], FCR_FIFO_ENABLE | FCR_RESETS)
        await ClockCycles(dut.clk_periph_i, BIT_CYCLES)
        await RisingEdge(dut.clk_periph_i)
        await FallingEdge(dut.clk_periph_i)
        await self._drive_rx_byte(CHECK_BYTE)
        got = await self._read_bytes(f"{tag}_CHECK", 1)
        assert got == [CHECK_BYTE], (
            f"{tag}: with the FIFO enabled again after an FCR write offset {offset} clocks "
            f"from the receive timeout, a received 0x{CHECK_BYTE:02x} read back as "
            f"{[hex(b) for b in got]}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        dut.tb_uart0_rx_ext_drive.value = 1
        cg = await self.csr_read("CG", CLOCK_GATE_CONTROL)
        await self.csr_write("CG_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._setup("SETUP")
        cocotb.start_soon(self._cable())
        self.path = await self._measure_path()
        for offset in OFFSETS:
            await self._empty_leg(f"EMPTY{offset + 2}", offset)
        cocotb.log.info(
            "CHK-UART-THR-ON-EMPTY: with the register path measured at %d clocks, a THR write "
            "was placed %s clocks from the transmit FIFO emptying, and every point delivered "
            "its three bytes in order over the TX-to-RX wire",
            self.path,
            list(OFFSETS),
        )
        for offset in OFFSETS:
            await self._timeout_leg(f"RXTO{offset + 2}", offset)
        await self.csr_write("FCR_RESTORE", self.r["iir"], 0)
        await self.csr_write("CG_RESTORE", CLOCK_GATE_CONTROL, cg)
        cocotb.log.info(
            "CHK-UART-FCR-ON-TIMEOUT: an FCR write clearing FIFO_ENABLE was placed %s clocks "
            "from the receive timeout, and after each point a byte received with the FIFO "
            "enabled again read back intact",
            list(OFFSETS),
        )
