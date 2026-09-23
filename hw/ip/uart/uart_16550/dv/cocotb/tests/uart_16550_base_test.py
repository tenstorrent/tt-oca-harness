# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the UART 16550 IP-level cocotb tests.

The bench drives three surfaces of ``uart_16550_tb_top``:

* the AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only);
* the serial line through the shared UART VIP: ``OcahUartMasterDriver`` on
  the DUT's ``rx`` pin and ``OcahUartLineMonitor`` sampling its ``tx`` pin;
* the modem, DMA-ready, error and interrupt pins directly.

Register addresses, field layouts and reset values come from the generated
RDL headers of the three register maps (main, write-only and divisor latch),
which share one base: the divisor latch registers alias RBR/THR and IER while
LCR.DLAB is set. Interrupt identifiers are the 16550 architectural codes that
``uart_16550_pkg::interrupt_id_e`` reproduces.

The baud clock is the DUT clock divided by ``16 * divisor``; the bench keeps
the divisor exact and derives the VIP's baud rate from it, so the line engines
and the DUT agree on the bit period to within the VIP's 1 ns rounding.
"""

from __future__ import annotations

import enum
import logging
import math
import os
from dataclasses import dataclass

import cocotb
import uart_16550_dl_reg as DL
import uart_16550_main_reg as MAIN
import uart_16550_main_wo_reg as WO
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import OcahAxiLiteMasterAgent
from ocah_uart_vip import OcahUartFrame, OcahUartLineMonitor, OcahUartMasterDriver

CLK_PERIOD_NS = 2
CLK_HZ = int(1e9 / CLK_PERIOD_NS)

# The bench's default baud divisor; the VIP baud rate follows from it.
BAUD_DIVISOR = 68
BAUD = round(CLK_HZ / (16 * BAUD_DIVISOR))

# tb_top parameters.
TX_FIFO_DEPTH = 16
RX_FIFO_DEPTH = 16

# The 16550 receiver reports a reception timeout after four character times
# without activity while the RX FIFO holds data (uart_16550_pkg::TIMEOUT_CHAR_CNT).
TIMEOUT_CHAR_CNT = 4

# Reception FIFO trigger levels selectable through FCR.RCVR_TRIGGER.
RX_TRIGGER_LEVELS = {1: 0b00, 4: 0b01, 8: 0b10, 14: 0b11}

# Slack applied to a character-time wait so a frame in flight completes.
WAIT_MARGIN = 1.25


class IntrId(enum.IntEnum):
    """IIR.INTERRUPT_ID codes, highest priority first."""

    FIFO_ERROR = 0x7
    RECEIVER_LINE_STATUS = 0x3
    RECEPTION_TIMEOUT = 0x6
    RECEIVED_DATA_READY = 0x2
    TRANSMITTER_HOLDING_REGISTER_EMPTY = 0x1
    MODEM_STATUS = 0x0


class DmaMode(enum.IntEnum):
    MODE_0 = 0
    MODE_1 = 1


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def reg_mask(reg_t) -> int:
    """Mask of the architected (non-reserved) bits of a generated register struct."""
    mask = 0
    offset = 0
    for name, _ctype, width in reg_t._fields_:
        if not name.startswith("rsvd"):
            mask |= ((1 << width) - 1) << offset
        offset += width
    return mask


def parity_name(enable: bool, even: bool) -> str:
    if not enable:
        return "none"
    return "even" if even else "odd"


def parity_of(value: int) -> int:
    """1 when ``value`` has an odd number of set bits."""
    return bin(value).count("1") & 1


def word_mask(word_length: int) -> int:
    return (1 << word_length) - 1


@dataclass(frozen=True)
class LineFormat:
    """One programmed line format and the timing that follows from it."""

    word_length: int = 8
    stop_bits: int = 1
    parity_enable: bool = True
    even_parity: bool = False
    divisor: int = BAUD_DIVISOR

    @property
    def parity(self) -> str:
        return parity_name(self.parity_enable, self.even_parity)

    @property
    def frame_bits(self) -> int:
        return 1 + self.word_length + int(self.parity_enable) + self.stop_bits

    @property
    def frame_cycles(self) -> int:
        """DUT clock cycles one frame occupies on the wire."""
        return self.frame_bits * 16 * self.divisor

    @property
    def frame_ns(self) -> int:
        return self.frame_cycles * CLK_PERIOD_NS

    @property
    def baud(self) -> int:
        return round(CLK_HZ / (16 * self.divisor))


class Uart16550Tb:
    """Clock/reset bring-up, register access, and line-level helpers."""

    def __init__(self, dut, name: str = "uart_16550_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self.line_driver = None
        self.line_sampler = None
        self.fmt = LineFormat()

    async def start(self) -> None:
        """Init inputs, start the clock, run reset, and bring up the VIPs."""
        dut = self.dut
        dut.rx.value = 1
        dut.cts_n.value = 1
        dut.dsr_n.value = 1
        dut.ri_n.value = 1
        dut.dcd_n.value = 1
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="uart_axil_host",
            timeout_cycles=1000,
        )
        self.seq = self.agent.sequence
        await self.agent.start()
        await self.reset()

        self.line_driver = OcahUartMasterDriver(
            dut.rx,
            name="uart_line_driver",
            baud=BAUD,
            bits=8,
            parity="none",
            stop_bits=1,
        )
        self.line_sampler = OcahUartLineMonitor(
            dut.tx,
            name="uart_line_sampler",
            baud=BAUD,
            bits=8,
            parity="none",
            stop_bits=1,
        )
        self.log.info(
            "bring-up complete: clk %d ns, divisor %d, baud %d", CLK_PERIOD_NS, BAUD_DIVISOR, BAUD
        )

    async def reset(self) -> None:
        """Pulse rst_n; the AXI master and the line engines idle through it."""
        dut = self.dut
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)
        if self.line_sampler is not None:
            self.line_sampler.clear()
            self.line_sampler.clear_history()

    # ------------------------------------------------------------------
    # Register access
    # ------------------------------------------------------------------

    async def write(self, addr: int, value: int) -> None:
        await self.seq.write(addr, value)

    async def read(self, addr: int) -> int:
        return await self.seq.read(addr)

    async def read_u(self, union_t, addr: int):
        """Read a register into its generated union so fields are addressable."""
        reg = union_t()
        reg.val = await self.read(addr)
        return reg

    # ------------------------------------------------------------------
    # Line format
    # ------------------------------------------------------------------

    async def configure(
        self,
        *,
        word_length: int = 8,
        stop_bits: int = 1,
        parity_enable: bool = True,
        even_parity: bool = False,
        loopback: bool = False,
        fifos: bool = False,
        divisor: int = BAUD_DIVISOR,
    ) -> LineFormat:
        """Program LCR/DLL/DLM/MCR/FCR and retune the line engines to match."""
        fmt = LineFormat(word_length, stop_bits, parity_enable, even_parity, divisor)

        lcr = MAIN.UART_16550_MAIN_LCR_reg_u()
        lcr.f.wls = word_length - 5
        lcr.f.stb = stop_bits - 1
        lcr.f.pen = int(parity_enable)
        lcr.f.eps = int(even_parity)
        lcr.f.dlab = 1
        await self.write(MAIN.LCR_REG_ADDR, lcr.val)
        await self.write(DL.DLL_REG_ADDR, divisor & 0xFF)
        await self.write(DL.DLM_REG_ADDR, (divisor >> 8) & 0xFF)
        lcr.f.dlab = 0
        await self.write(MAIN.LCR_REG_ADDR, lcr.val)

        mcr = MAIN.UART_16550_MAIN_MCR_reg_u()
        mcr.f.loop = int(loopback)
        await self.write(MAIN.MCR_REG_ADDR, mcr.val)

        fcr = WO.UART_16550_MAIN_WO_FCR_reg_u()
        fcr.f.fifo_enable = int(fifos)
        await self.write(WO.FCR_REG_ADDR, fcr.val)

        self.apply_line_format(fmt)
        self.log.info(
            "line format: %d%s%d divisor %d (baud %d, %d cycles/frame) loopback=%d fifos=%d",
            word_length,
            fmt.parity[0].upper(),
            stop_bits,
            divisor,
            fmt.baud,
            fmt.frame_cycles,
            loopback,
            fifos,
        )
        return fmt

    def apply_line_format(self, fmt: LineFormat) -> None:
        self.fmt = fmt
        for engine in (self.line_driver, self.line_sampler):
            engine.configure(bits=fmt.word_length, parity=fmt.parity, stop_bits=fmt.stop_bits)
            engine.baud = fmt.baud
        self.line_sampler.clear()
        self.line_sampler.clear_history()

    # ------------------------------------------------------------------
    # Line-level helpers
    # ------------------------------------------------------------------

    async def wait_frames(self, count: float) -> None:
        """Wait ``count`` character times of the programmed format, plus margin."""
        await ClockCycles(self.dut.clk, int(math.ceil(WAIT_MARGIN * count * self.fmt.frame_cycles)))

    async def expect_frames(
        self, count: int, what: str, timeout_frames: float = 4
    ) -> list[OcahUartFrame]:
        """Sample ``count`` frames from tx within a bounded number of frame times."""
        budget_ns = int(math.ceil((count + timeout_frames) * self.fmt.frame_ns * WAIT_MARGIN))
        frames = await with_timeout(self.line_sampler.read_frames(count), budget_ns, "ns")
        for index, frame in enumerate(frames):
            assert frame.clean, f"{what}: frame {index} 0x{frame.data:02x} flagged {frame.flags}"
        return frames

    async def wait_data_ready(self, what: str, timeout_frames: int = 8):
        """Poll LSR until DR is set; returns the LSR value that reported it."""
        for _ in range(timeout_frames):
            lsr = await self.read_u(MAIN.UART_16550_MAIN_LSR_reg_u, MAIN.LSR_REG_ADDR)
            if lsr.f.dr:
                return lsr
            await ClockCycles(self.dut.clk, self.fmt.frame_cycles)
        raise AssertionError(f"{what}: LSR.DR never set within {timeout_frames} frame times")

    async def send_chars(self, chars: list[int]) -> None:
        """Queue characters on the DUT's rx pin through the VIP line driver."""
        await self.line_driver.write(chars)

    async def read_iir(self):
        return await self.read_u(MAIN.UART_16550_MAIN_IIR_reg_u, MAIN.IIR_REG_ADDR)

    async def expect_irq(self, intr_id: IntrId, what: str) -> None:
        """irq is high and IIR identifies ``intr_id`` as the pending source."""
        await ClockCycles(self.dut.clk, 10)
        assert int(self.dut.irq.value) == 1, f"{what}: irq not raised"
        iir = await self.read_iir()
        assert iir.f.interrupt_pending == 0, f"{what}: IIR reports no interrupt pending"
        assert iir.f.interrupt_id == intr_id, (
            f"{what}: IIR id expected {intr_id.name} (0x{intr_id:x}), observed 0x{iir.f.interrupt_id:x}"
        )
        self.log.info("%s: irq raised with IIR id %s", what, intr_id.name)


__all__ = [
    "BAUD",
    "BAUD_DIVISOR",
    "CLK_PERIOD_NS",
    "DL",
    "MAIN",
    "RX_FIFO_DEPTH",
    "RX_TRIGGER_LEVELS",
    "TIMEOUT_CHAR_CNT",
    "TX_FIFO_DEPTH",
    "WAIT_MARGIN",
    "WO",
    "DmaMode",
    "IntrId",
    "LineFormat",
    "Uart16550Tb",
    "parity_of",
    "random_seed",
    "reg_mask",
    "word_mask",
]
