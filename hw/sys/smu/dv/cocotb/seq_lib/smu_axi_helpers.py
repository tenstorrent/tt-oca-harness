# SPDX-License-Identifier: Apache-2.0
"""Shared AXI-Lite-over-AXI64 helpers for SMU external SMN port."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotbext.axi import AxiBus, AxiMaster


async def make_smu_axi_master(dut, clk, reset) -> AxiMaster:
    bus = AxiBus.from_prefix(dut, "s_axi")
    master = AxiMaster(bus, clk, reset, reset_active_level=False)
    await Timer(1, units="ns")
    return master


async def axi_read32(master: AxiMaster, addr: int) -> int:
    data = await master.read(addr, 4)
    return int.from_bytes(bytes(data.data), byteorder="little")


async def axi_read32_resp(master: AxiMaster, addr: int) -> tuple[int, object]:
    """Return (rdata32, AxiResp) so callers can assert DECERR vs OKAY."""
    beat = await master.read(addr, 4)
    value = int.from_bytes(bytes(beat.data), byteorder="little")
    return value, beat.resp


async def axi_write32(master: AxiMaster, addr: int, value: int) -> None:
    await master.write(addr, value.to_bytes(4, byteorder="little"))


async def axi_write32_resp(master: AxiMaster, addr: int, value: int) -> object:
    """Return AxiResp from a 32-bit write."""
    beat = await master.write(addr, value.to_bytes(4, byteorder="little"))
    return beat.resp


async def wait_signal_high(signal, clk, timeout_cycles: int = 5000, name: str = "sig") -> None:
    for _ in range(timeout_cycles):
        await RisingEdge(clk)
        try:
            if int(signal.value) == 1:
                return
        except ValueError:
            pass
    raise AssertionError(f"timeout waiting for {name}==1")
