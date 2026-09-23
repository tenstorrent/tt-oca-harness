# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the Log Engine IP-level cocotb tests.

The bench drives four surfaces of ``log_engine_tb_top``:

* the AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only);
* the 64-bit log-fetch master port, answered by a VIP memory responder
  (``OcahAxiLiteSlaveAgent`` on ``log_fetch_*``) that holds the log region;
* the 32-bit log-write master port, answered by a second VIP responder on
  ``log_write_*`` and observed by ``OcahAxiLiteMonitor``, whose write items
  are the byte stream the engine hands to the UART;
* the ``uart_tx_ready`` pacing input and the ``irq`` output.

Register addresses, field layouts and reset values come from the generated
RDL header; the slot geometry mirrors the RDL's LOG_REGION_SIZE contract: the
region (clamped to 512 KiB) is divided equally among the log entries, and a
slot moves at most its capacity rounded down to whole 8-byte fetch beats.
"""

from __future__ import annotations

import logging
import os

import cocotb
import log_engine_reg as REG
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from ocah_axi_vip import OcahAxiLiteMasterAgent, OcahAxiLiteMonitor, OcahAxiLiteSlaveAgent

CLK_PERIOD_NS = 10

# Log entries: one LOG_CTRL register each in the generated header.
LOG_CTRL_ADDRS: list[int] = []
while hasattr(REG, f"LOG_CTRL_{len(LOG_CTRL_ADDRS)}__REG_ADDR"):
    LOG_CTRL_ADDRS.append(getattr(REG, f"LOG_CTRL_{len(LOG_CTRL_ADDRS)}__REG_ADDR"))
NUM_LOG_ENTRIES = len(LOG_CTRL_ADDRS)

# Bytes per log-fetch beat (the 64-bit fetch port) and the RDL's region limits.
FETCH_BEAT_BYTES = 8
MAX_LOG_REGION_SIZE = 512 * 1024
LOG_REGION_ALIGNMENT = NUM_LOG_ENTRIES * FETCH_BEAT_BYTES
LOG_LEN_MAX = (1 << 16) - 1

# LOG_REGION_ADDR is a 64-bit register accessed as two 32-bit words.
LOG_REGION_ADDR_LO_ADDR = REG.LOG_REGION_ADDR_REG_ADDR
LOG_REGION_ADDR_HI_ADDR = REG.LOG_REGION_ADDR_REG_ADDR + 4

# Bench memory map on the two responders.
FETCH_RAM_SIZE = 1 << 20
WRITE_RAM_SIZE = 1 << 12
REGION_ADDR = 0x1000
WRITE_ADDR = 0x100

# Upper bound on the cycles one byte needs end to end: a fetch beat every
# eight bytes plus one write handshake per byte, each a few cycles when the
# responders never stall.
CYCLES_PER_BYTE = 16


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
    """Bytes between consecutive slot bases (the region divided by the entry count)."""
    return min(region_size, MAX_LOG_REGION_SIZE) // NUM_LOG_ENTRIES


def slot_capacity(region_size: int) -> int:
    """Bytes one slot can transfer: its stride rounded down to whole fetch beats."""
    return (slot_stride(region_size) // FETCH_BEAT_BYTES) * FETCH_BEAT_BYTES


def slot_base(region_addr: int, region_size: int, index: int) -> int:
    return region_addr + slot_stride(region_size) * index


class LogEngineTb:
    """Clock/reset bring-up, VIPs on the three ports, and transfer helpers."""

    def __init__(self, dut, name: str = "log_engine_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self.fetch_ram = None
        self.write_ram = None
        self.write_mon = None
        self.written: list[tuple[int, int]] = []
        self.region_addr = REGION_ADDR
        self.region_size = 0

    async def start(self) -> None:
        """Init inputs, start the clock, bring up the VIPs, and run reset."""
        dut = self.dut
        dut.uart_tx_ready.value = 1
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="log_engine_axil_host",
            timeout_cycles=1000,
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
        self.write_ram = OcahAxiLiteSlaveAgent.from_prefix(
            dut,
            "log_write",
            dut.clk,
            dut.rst_n,
            reset_active_level=False,
            size=WRITE_RAM_SIZE,
            name="log_write_sink",
        ).sequence
        self.write_mon = OcahAxiLiteMonitor.from_prefix(
            dut, "log_write", dut.clk, name="log_write_mon"
        )
        self.write_mon.add_write_callback(self._on_write)
        await self.write_mon.start()

        await self.reset()
        self.log.info(
            "bring-up complete: %d log entries, region at 0x%x, UART sink at 0x%x",
            NUM_LOG_ENTRIES,
            REGION_ADDR,
            WRITE_ADDR,
        )

    async def reset(self) -> None:
        dut = self.dut
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)
        self.written.clear()

    def _on_write(self, item) -> None:
        # The engine writes one byte per transaction in the low lane.
        self.written.append((item.address, item.data_words[0] & 0xFF))

    # ------------------------------------------------------------------
    # Register access
    # ------------------------------------------------------------------

    async def write(self, addr: int, value: int) -> None:
        await self.seq.write(addr, value)

    async def read(self, addr: int) -> int:
        return await self.seq.read(addr)

    async def read_u(self, union_t, addr: int):
        reg = union_t()
        reg.val = await self.read(addr)
        return reg

    # ------------------------------------------------------------------
    # Engine configuration and transfers
    # ------------------------------------------------------------------

    async def configure(
        self,
        region_size: int,
        *,
        region_addr: int = REGION_ADDR,
        write_addr: int = WRITE_ADDR,
        enable: bool = True,
    ) -> None:
        """Disable, program the region and UART target, then (re)enable."""
        await self.write(REG.CTRL_REG_ADDR, 0)
        await self.write(REG.LOG_REGION_SIZE_REG_ADDR, region_size)
        await self.write(LOG_REGION_ADDR_LO_ADDR, region_addr & 0xFFFF_FFFF)
        await self.write(LOG_REGION_ADDR_HI_ADDR, region_addr >> 32)
        await self.write(REG.LOG_WRITE_ADDR_REG_ADDR, write_addr)
        await self.write(REG.CTRL_REG_ADDR, int(enable))
        self.region_addr = region_addr
        self.region_size = region_size
        self.log.info(
            "configured: region 0x%x size %d (slot stride %d, capacity %d), UART at 0x%x, en=%d",
            region_addr,
            region_size,
            slot_stride(region_size),
            slot_capacity(region_size),
            write_addr,
            enable,
        )

    def load_slot(self, index: int, payload: bytes) -> int:
        """Backdoor the payload into the slot's region; returns the slot base."""
        base = slot_base(self.region_addr, self.region_size, index)
        self.fetch_ram.write(base, payload)
        return base

    async def arm(self, index: int, length: int) -> None:
        await self.write(LOG_CTRL_ADDRS[index], length)

    async def wait_done(self, index: int, budget_cycles: int, what: str) -> None:
        """Poll LOG_CTRL until the engine cleared the length."""
        waited = 0
        while True:
            remaining = await self.read(LOG_CTRL_ADDRS[index])
            if remaining == 0:
                return
            assert waited < budget_cycles, (
                f"{what}: slot {index} still reports {remaining} bytes after {waited} cycles"
            )
            await ClockCycles(self.dut.clk, 20)
            waited += 20

    def drain_written(self) -> list[int]:
        """The bytes written to the UART sink since the last drain, in order."""
        for address, _ in self.written:
            assert address == WRITE_ADDR, (
                f"log write to 0x{address:x}, expected the UART sink at 0x{WRITE_ADDR:x}"
            )
        data = [byte for _, byte in self.written]
        self.written.clear()
        return data

    async def transfer(
        self, index: int, payload: bytes, what: str, length: int | None = None
    ) -> list[int]:
        """Load, arm, wait, and return the byte stream the engine wrote."""
        self.load_slot(index, payload)
        self.written.clear()
        await self.arm(index, len(payload) if length is None else length)
        await self.wait_done(index, CYCLES_PER_BYTE * max(len(payload), 1) + 400, what)
        await ClockCycles(self.dut.clk, 20)
        return self.drain_written()


__all__ = [
    "CLK_PERIOD_NS",
    "CYCLES_PER_BYTE",
    "FETCH_BEAT_BYTES",
    "LOG_CTRL_ADDRS",
    "LOG_LEN_MAX",
    "LOG_REGION_ADDR_HI_ADDR",
    "LOG_REGION_ADDR_LO_ADDR",
    "LOG_REGION_ALIGNMENT",
    "MAX_LOG_REGION_SIZE",
    "NUM_LOG_ENTRIES",
    "REG",
    "REGION_ADDR",
    "WRITE_ADDR",
    "LogEngineTb",
    "random_seed",
    "reg_mask",
    "slot_base",
    "slot_capacity",
    "slot_stride",
]
