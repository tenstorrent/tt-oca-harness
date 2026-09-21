# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the UART wrapper IP-level cocotb tests.

The bench drives four surfaces of ``uart_wrap_tb_top``:

* the wrapper's AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite
  master (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins,
  consumed through ``agent.sequence`` only) — one UART-and-log-engine window
  per instance at the wrapper's instance spacing;
* the shared 64-bit log-fetch master port, answered by a VIP memory
  responder (``OcahAxiLiteSlaveAgent`` on ``log_fetch_*``);
* each UART's serial line through the shared UART VIP's line driver
  (``uart_rx_<i>``) and sampler (``uart_tx_<i>``);
* the packed ``uart_en``, modem, DMA-ready, error and interrupt pins.

The instance count, window bases, register addresses, field layouts and
reset values come from the wrapper's generated RDL header, which flattens
every instance's embedded maps under ``UART_LOG_ENGINE_WRAP_<i>__``.
"""

from __future__ import annotations

import logging
import math
import os

import cocotb
import uart_wrap_reg as REG
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
FRAME_CYCLES = 10 * 16 * BAUD_DIVISOR
FRAME_NS = FRAME_CYCLES * CLK_PERIOD_NS

# Instances: one flattened window each in the generated header.
WINDOW_BASES: list[int] = []
while hasattr(REG, f"UART_LOG_ENGINE_WRAP_{len(WINDOW_BASES)}__REG_MAP_BASE_ADDR"):
    WINDOW_BASES.append(
        getattr(REG, f"UART_LOG_ENGINE_WRAP_{len(WINDOW_BASES)}__REG_MAP_BASE_ADDR")
    )
NUM_UARTS = len(WINDOW_BASES)
WINDOW_STRIDE = WINDOW_BASES[1] - WINDOW_BASES[0]

# Log engine geometry (log entries per engine, bytes per fetch beat).
NUM_LOG_ENTRIES = 16
FETCH_BEAT_BYTES = 8
FETCH_RAM_SIZE = 1 << 20
REGION_ADDR = 0x1000

# The wrapper's error responders answer unmapped addresses with DECERR and
# this read payload.
DECERR_RDATA = 0xBADC_AB1E


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


def win(index: int, name: str) -> int:
    """Address of ``name`` (a flattened register or map base) in instance ``index``'s window."""
    return getattr(REG, f"UART_LOG_ENGINE_WRAP_{index}__{name}")


def bit(vector, index: int) -> int:
    return (int(vector.value) >> index) & 1


class UartWrapTb:
    """Clock/reset bring-up, VIPs on every surface, and per-instance helpers."""

    def __init__(self, dut, name: str = "uart_wrap_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self.fetch_ram = None
        self.line_drivers: list[OcahUartMasterDriver] = []
        self.line_samplers: list[OcahUartLineMonitor] = []

    async def start(self) -> None:
        dut = self.dut
        all_ones = (1 << NUM_UARTS) - 1
        for index in range(NUM_UARTS):
            getattr(dut, f"uart_rx_{index}").value = 1
        dut.uart_cts_n.value = all_ones
        dut.uart_dsr_n.value = all_ones
        dut.uart_ri_n.value = all_ones
        dut.uart_dcd_n.value = all_ones
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="uart_wrap_axil_host",
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

        for index in range(NUM_UARTS):
            self.line_drivers.append(
                OcahUartMasterDriver(
                    getattr(dut, f"uart_rx_{index}"),
                    name=f"uart{index}_line_driver",
                    baud=BAUD,
                    bits=8,
                    parity="none",
                    stop_bits=1,
                )
            )
            self.line_samplers.append(
                OcahUartLineMonitor(
                    getattr(dut, f"uart_tx_{index}"),
                    name=f"uart{index}_line_sampler",
                    baud=BAUD,
                    bits=8,
                    parity="none",
                    stop_bits=1,
                )
            )
        self.log.info(
            "bring-up complete: %d UARTs at stride 0x%x, baud %d", NUM_UARTS, WINDOW_STRIDE, BAUD
        )

    async def reset(self) -> None:
        dut = self.dut
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)
        for sampler in self.line_samplers:
            sampler.clear()
            sampler.clear_history()

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
    # Per-instance programming
    # ------------------------------------------------------------------

    async def configure_uart(self, index: int, *, divisor: int = BAUD_DIVISOR) -> None:
        """Program instance ``index``'s UART for 8N1 at the bench divisor."""
        lcr = REG.UART_16550_MAIN_LCR_reg_u()
        lcr.f.wls = 8 - 5
        lcr.f.dlab = 1
        await self.write(win(index, "UART_LCR_REG_ADDR"), lcr.val)
        await self.write(win(index, "UART_RBR_REG_ADDR"), divisor & 0xFF)
        await self.write(win(index, "UART_IER_REG_ADDR"), (divisor >> 8) & 0xFF)
        lcr.f.dlab = 0
        await self.write(win(index, "UART_LCR_REG_ADDR"), lcr.val)
        self.line_samplers[index].clear()
        self.line_samplers[index].clear_history()

    async def configure_log_engine(self, index: int, region_size: int, *, region_addr: int) -> None:
        """Point instance ``index``'s log engine at its region and its own UART THR."""
        base = win(index, "LOG_ENGINE_CTRL_REG_ADDR")
        await self.write(base, 0)
        await self.write(win(index, "LOG_ENGINE_LOG_REGION_SIZE_REG_ADDR"), region_size)
        await self.write(
            win(index, "LOG_ENGINE_LOG_REGION_ADDR_REG_ADDR"), region_addr & 0xFFFF_FFFF
        )
        await self.write(win(index, "LOG_ENGINE_LOG_REGION_ADDR_REG_ADDR") + 4, region_addr >> 32)
        await self.write(
            win(index, "LOG_ENGINE_LOG_WRITE_ADDR_REG_ADDR"), win(index, "UART_RBR_REG_ADDR")
        )
        await self.write(base, 1)

    async def expect_frames(
        self, index: int, count: int, what: str, slack_frames: float = 4
    ) -> list[OcahUartFrame]:
        budget_ns = int(math.ceil((count + slack_frames) * FRAME_NS * 1.25))
        frames = await with_timeout(self.line_samplers[index].read_frames(count), budget_ns, "ns")
        for position, frame in enumerate(frames):
            assert frame.clean, (
                f"{what}: uart{index} frame {position} 0x{frame.data:02x} flagged {frame.flags}"
            )
        return frames

    async def wait_data_ready(self, index: int, what: str, timeout_frames: int = 8):
        for _ in range(timeout_frames):
            lsr = await self.read_u(REG.UART_16550_MAIN_LSR_reg_u, win(index, "UART_LSR_REG_ADDR"))
            if lsr.f.dr:
                return lsr
            await ClockCycles(self.dut.clk, FRAME_CYCLES)
        raise AssertionError(
            f"{what}: uart{index} LSR.DR never set within {timeout_frames} frame times"
        )

    def idle_lines(self, except_index: int) -> list[int]:
        """Indices of the other UARTs whose tx pin is not at the idle level."""
        busy = []
        for index in range(NUM_UARTS):
            if index != except_index and int(getattr(self.dut, f"uart_tx_{index}").value) != 1:
                busy.append(index)
        return busy


__all__ = [
    "BAUD",
    "BAUD_DIVISOR",
    "CLK_PERIOD_NS",
    "DECERR_RDATA",
    "FETCH_BEAT_BYTES",
    "FRAME_CYCLES",
    "NUM_LOG_ENTRIES",
    "NUM_UARTS",
    "REG",
    "REGION_ADDR",
    "WINDOW_BASES",
    "WINDOW_STRIDE",
    "UartWrapTb",
    "bit",
    "random_seed",
    "reg_mask",
    "win",
]
