# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the UART and Log Engine wrapper IP-level cocotb tests.

The bench drives four surfaces of ``uart_log_engine_wrap_tb_top``:

* the wrapper's AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite
  master (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins,
  consumed through ``agent.sequence`` only) — the control block, the UART
  and the log engine each sit in their own window of the wrapper map;
* the 64-bit log-fetch master port, answered by a VIP memory responder
  (``OcahAxiLiteSlaveAgent`` on ``log_fetch_*``) that holds the log region;
* the serial line through the shared UART VIP's line driver (``uart_rx``)
  and sampler (``uart_tx``);
* the ``uart_en``, modem, DMA-ready, error and interrupt pins directly.

Window bases, register addresses, field layouts and reset values come from
the wrapper's generated RDL header, which flattens the embedded UART 16550
and log engine maps under their window prefixes. The log engine's write port
is wired inside the wrapper to the UART's register port, so a log transfer
programmed at the UART's THR address leaves the wrapper on ``uart_tx``.
"""

from __future__ import annotations

import logging
import math
import os

import cocotb
import uart_log_engine_wrap_reg as REG
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, with_timeout
from ocah_axi_vip import OcahAxiLiteMasterAgent, OcahAxiLiteSlaveAgent
from ocah_uart_vip import OcahUartFrame, OcahUartLineMonitor, OcahUartMasterDriver

CLK_PERIOD_NS = 2
CLK_HZ = int(1e9 / CLK_PERIOD_NS)

# The bench's baud divisor; the VIP baud rate follows from it.
BAUD_DIVISOR = 68
BAUD = round(CLK_HZ / (16 * BAUD_DIVISOR))

# 8N1 frame time in DUT cycles at the bench divisor.
FRAME_BITS = 10
FRAME_CYCLES = FRAME_BITS * 16 * BAUD_DIVISOR
FRAME_NS = FRAME_CYCLES * CLK_PERIOD_NS

# UART 16550 register offsets inside the UART window, from the flattened header.
UART_THR_ADDR = REG.UART_RBR_REG_ADDR  # THR shares the RBR offset (write side)
UART_DLL_ADDR = REG.UART_RBR_REG_ADDR  # divisor latch low aliases RBR/THR while LCR.DLAB is set
UART_DLM_ADDR = REG.UART_IER_REG_ADDR  # divisor latch high aliases IER while LCR.DLAB is set
UART_FCR_ADDR = REG.UART_IIR_REG_ADDR  # FCR shares the IIR offset (write side)

# Log entries: one LOG_CTRL register each in the flattened header.
LOG_CTRL_ADDRS: list[int] = []
while hasattr(REG, f"LOG_ENGINE_LOG_CTRL_{len(LOG_CTRL_ADDRS)}__REG_ADDR"):
    LOG_CTRL_ADDRS.append(getattr(REG, f"LOG_ENGINE_LOG_CTRL_{len(LOG_CTRL_ADDRS)}__REG_ADDR"))
NUM_LOG_ENTRIES = len(LOG_CTRL_ADDRS)
FETCH_BEAT_BYTES = 8
LOG_REGION_ADDR_LO_ADDR = REG.LOG_ENGINE_LOG_REGION_ADDR_REG_ADDR
LOG_REGION_ADDR_HI_ADDR = REG.LOG_ENGINE_LOG_REGION_ADDR_REG_ADDR + 4

# Bench memory map on the fetch responder.
FETCH_RAM_SIZE = 1 << 20
REGION_ADDR = 0x1000

# The wrapper's error responder answers unmapped addresses with DECERR and
# this read payload.
DECERR_RDATA = 0xBADC_AB1E
UNMAPPED_ADDRS = (
    REG.UART_LOG_ENGINE_WRAP_REG_MAP_SIZE,
    REG.UART_REG_MAP_BASE_ADDR + REG.UART_REG_MAP_SIZE,
    REG.LOG_ENGINE_REG_MAP_BASE_ADDR + REG.LOG_ENGINE_REG_MAP_SIZE,
)


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def reg_mask(reg_t) -> int:
    """Mask of the architected (non-reserved) bits of a generated register struct."""
    mask = 0
    offset = 0
    for name, _ctype, width in reg_t._fields_:
        if not name.startswith(("rsvd", "reserved")):
            mask |= ((1 << width) - 1) << offset
        offset += width
    return mask


def slot_stride(region_size: int) -> int:
    return region_size // NUM_LOG_ENTRIES


def slot_capacity(region_size: int) -> int:
    return (slot_stride(region_size) // FETCH_BEAT_BYTES) * FETCH_BEAT_BYTES


class UartLogEngineWrapTb:
    """Clock/reset bring-up, VIPs, and the wrapper's programming helpers."""

    def __init__(self, dut, name: str = "uart_log_engine_wrap_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self.fetch_ram = None
        self.line_driver = None
        self.line_sampler = None
        self.region_size = 0

    async def start(self) -> None:
        dut = self.dut
        dut.uart_rx.value = 1
        dut.uart_cts_n.value = 1
        dut.uart_dsr_n.value = 1
        dut.uart_ri_n.value = 1
        dut.uart_dcd_n.value = 1
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="wrap_axil_host",
            timeout_cycles=1000,
            raise_on_error=False,
        )
        self.seq = self.agent.sequence
        await self.agent.start()

        self.fetch_ram = OcahAxiLiteSlaveAgent.from_prefix(
            dut,
            "log_fetch",
            dut.clk,
            dut.rst_n,
            reset_active_level=False,
            size=FETCH_RAM_SIZE,
            name="log_fetch_ram",
        ).sequence

        await self.reset()

        self.line_driver = OcahUartMasterDriver(
            dut.uart_rx, name="uart_line_driver", baud=BAUD, bits=8, parity="none", stop_bits=1
        )
        self.line_sampler = OcahUartLineMonitor(
            dut.uart_tx, name="uart_line_sampler", baud=BAUD, bits=8, parity="none", stop_bits=1
        )
        self.log.info(
            "bring-up complete: %d log entries, baud %d, region at 0x%x",
            NUM_LOG_ENTRIES,
            BAUD,
            REGION_ADDR,
        )

    async def reset(self) -> None:
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
        result = await self.seq.write_result(addr, value)
        assert result.ok, f"write 0x{addr:x}: response 0x{result.resp:x}"

    async def read(self, addr: int) -> int:
        result = await self.seq.read_result(addr)
        assert result.ok, f"read 0x{addr:x}: response 0x{result.resp:x}"
        return result.data

    async def read_u(self, union_t, addr: int):
        reg = union_t()
        reg.val = await self.read(addr)
        return reg

    async def read_result(self, addr: int):
        return await self.seq.read_result(addr, check_response=False)

    async def write_result(self, addr: int, value: int):
        return await self.seq.write_result(addr, value, check_response=False)

    # ------------------------------------------------------------------
    # UART and log engine programming
    # ------------------------------------------------------------------

    async def configure_uart(self, *, divisor: int = BAUD_DIVISOR, fifos: bool = False) -> None:
        """Program the embedded UART for 8N1 at the bench divisor."""
        lcr = REG.UART_16550_MAIN_LCR_reg_u()
        lcr.f.wls = 8 - 5
        lcr.f.dlab = 1
        await self.write(REG.UART_LCR_REG_ADDR, lcr.val)
        await self.write(UART_DLL_ADDR, divisor & 0xFF)
        await self.write(UART_DLM_ADDR, (divisor >> 8) & 0xFF)
        lcr.f.dlab = 0
        await self.write(REG.UART_LCR_REG_ADDR, lcr.val)
        await self.write(UART_FCR_ADDR, int(fifos))
        self.line_sampler.clear()
        self.line_sampler.clear_history()
        self.log.info("UART programmed: 8N1, divisor %d (baud %d), fifos=%d", divisor, BAUD, fifos)

    async def configure_log_engine(
        self, region_size: int, *, region_addr: int = REGION_ADDR
    ) -> None:
        """Point the log engine at the fetch region and at the UART's THR, then enable it."""
        await self.write(REG.LOG_ENGINE_CTRL_REG_ADDR, 0)
        await self.write(REG.LOG_ENGINE_LOG_REGION_SIZE_REG_ADDR, region_size)
        await self.write(LOG_REGION_ADDR_LO_ADDR, region_addr & 0xFFFF_FFFF)
        await self.write(LOG_REGION_ADDR_HI_ADDR, region_addr >> 32)
        await self.write(REG.LOG_ENGINE_LOG_WRITE_ADDR_REG_ADDR, UART_THR_ADDR)
        await self.write(REG.LOG_ENGINE_CTRL_REG_ADDR, 1)
        self.region_size = region_size
        self.log.info(
            "log engine programmed: region 0x%x size %d (slot capacity %d), UART THR at 0x%x",
            region_addr,
            region_size,
            slot_capacity(region_size),
            UART_THR_ADDR,
        )

    def load_slot(self, index: int, payload: bytes) -> int:
        base = REGION_ADDR + slot_stride(self.region_size) * index
        self.fetch_ram.write(base, payload)
        return base

    async def wait_slot_done(self, index: int, budget_cycles: int, what: str) -> None:
        waited = 0
        while True:
            remaining = await self.read(LOG_CTRL_ADDRS[index])
            if remaining == 0:
                return
            assert waited < budget_cycles, (
                f"{what}: slot {index} still reports {remaining} bytes after {waited} cycles"
            )
            await ClockCycles(self.dut.clk, FRAME_CYCLES // 4)
            waited += FRAME_CYCLES // 4

    async def expect_frames(
        self, count: int, what: str, slack_frames: float = 4
    ) -> list[OcahUartFrame]:
        budget_ns = int(math.ceil((count + slack_frames) * FRAME_NS * 1.25))
        frames = await with_timeout(self.line_sampler.read_frames(count), budget_ns, "ns")
        for index, frame in enumerate(frames):
            assert frame.clean, f"{what}: frame {index} 0x{frame.data:02x} flagged {frame.flags}"
        return frames


__all__ = [
    "BAUD",
    "BAUD_DIVISOR",
    "CLK_PERIOD_NS",
    "DECERR_RDATA",
    "FRAME_CYCLES",
    "LOG_CTRL_ADDRS",
    "NUM_LOG_ENTRIES",
    "REG",
    "REGION_ADDR",
    "UART_THR_ADDR",
    "UNMAPPED_ADDRS",
    "UartLogEngineWrapTb",
    "random_seed",
    "reg_mask",
    "slot_capacity",
    "slot_stride",
]
