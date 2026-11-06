# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench for the prim_axil_addr_demux IP-level cocotb tests.

``prim_axil_addr_demux_tb_top`` places the ranges in ``RANGES`` inside the 4 KiB window at
``WINDOW_BASE``. Each range is answered by a responder that returns OKAY with read data
``RANGE_TAG | i`` for range ``i``, so a read names the range that answered, and the top's
``range_aw_count`` counts the write addresses each range accepts. Every other address must
reach the demux's own responder, which answers SLVERR with read data 0.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, OcahAxiLiteMasterAgent

CLK_PERIOD_NS = 2
WINDOW_BASE = 0xC000_C000
WINDOW_SIZE = 0x1000
RANGE_TAG = 0x5107_0000
# (offset in the window, size in bytes) per range, as tb/tb_top.sv places them.
RANGES = ((0x000, 0x20), (0x020, 0x20), (0x100, 0x10), (0x200, 0xC), (0x800, 0x150))


def range_index(addr: int) -> int | None:
    """Index of the range holding ``addr``, or None for spare space."""
    for index, (offset, size) in enumerate(RANGES):
        if WINDOW_BASE + offset <= addr < WINDOW_BASE + offset + size:
            return index
    return None


def expected(addr: int) -> tuple[int, int]:
    """Response code and read data the demux must give at ``addr``."""
    index = range_index(addr)
    if index is None:
        return RESP_SLVERR, 0
    return RESP_OKAY, RANGE_TAG | index


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


class AddrDemuxTb:
    """Clock and reset bring-up and the checked accesses."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.seq = None

    async def start(self) -> None:
        dut = self.dut
        dut.rst_n.value = 0
        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
        agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="addr_demux_host",
            timeout_cycles=1000,
            raise_on_error=False,
        )
        self.seq = agent.sequence
        await agent.start()
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 10)

    def aw_counts(self) -> list[int]:
        value = int(self.dut.range_aw_count.value)
        return [(value >> (8 * i)) & 0xFF for i in range(len(RANGES))]

    async def check_read(self, addr: int) -> None:
        want_resp, want_data = expected(addr)
        got = await self.seq.read_result(addr, check_response=False)
        assert (got.resp, got.data) == (want_resp, want_data), (
            f"read 0x{addr:08x}: expected resp {want_resp} data 0x{want_data:08x}, "
            f"observed resp {got.resp} data 0x{got.data:08x}"
        )

    async def check_write(self, addr: int, value: int) -> None:
        """Write ``addr`` and check the response and which ranges accepted the address."""
        want_resp, _ = expected(addr)
        index = range_index(addr)
        want_ranges = [] if index is None else [index]
        before = self.aw_counts()
        got = await self.seq.write_result(addr, value, check_response=False)
        after = self.aw_counts()
        ranges = [i for i in range(len(RANGES)) for _ in range((after[i] - before[i]) % 256)]
        assert (got.resp, ranges) == (want_resp, want_ranges), (
            f"write 0x{addr:08x}: expected resp {want_resp} reaching ranges {want_ranges}, "
            f"observed resp {got.resp} reaching ranges {ranges}"
        )
