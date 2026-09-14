# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import logging
import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.append(os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))

from entropy_source_reg import *

REG_ADDR_WIDTH = 8
REG_DATA_WIDTH = 32


async def apb_write(dut, addr: int, data: int, mask=2 ** (REG_DATA_WIDTH // 8) - 1) -> None:
    """
    Write data to an APB register at the specified address.
    """
    await RisingEdge(dut.clk_i)
    dut.paddr_i.value = addr
    dut.pprot_i.value = 0x0
    dut.psel_i.value = 1
    dut.pwrite_i.value = 1
    dut.pwdata_i.value = data
    dut.pstrb_i.value = mask
    await RisingEdge(dut.clk_i)
    dut.penable_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.psel_i.value = 0
    dut.penable_i.value = 0


async def apb_read(dut, addr: int) -> int:
    """
    Read data from an APB register at the specified address.
    """
    await RisingEdge(dut.clk_i)
    dut.paddr_i.value = addr
    dut.psel_i.value = 1
    dut.pwrite_i.value = 0
    await RisingEdge(dut.clk_i)
    dut.penable_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.psel_i.value = 0
    dut.penable_i.value = 0
    return int(dut.prdata_o.value)


async def reg_write(dut, addr: int, data: int) -> None:
    """
    Write data to a register at the specified address.
    """
    log = logging.getLogger("cocotb.tb")
    log.info(f"Writing 0x{data:x} to register at address 0x{addr:x}.")
    await apb_write(dut, addr, data)


async def reg_read(dut, addr: int) -> int:
    """
    Read data from a register at the specified address.
    """
    log = logging.getLogger("cocotb.tb")
    log.info(f"Reading register at address 0x{addr:x}.")
    data = await apb_read(dut, addr)
    log.info(f"Read 0x{data:x} from register at address 0x{addr:x}.")
    return data


async def init_entropy_source(dut) -> None:
    # Global Interface
    dut.clk_i.value = 0
    dut.rst_ni.value = 0

    # APB4 Register Interface
    dut.paddr_i.value = 0x0
    dut.pprot_i.value = 0x0
    dut.psel_i.value = 0
    dut.penable_i.value = 0
    dut.pwrite_i.value = 0
    dut.pwdata_i.value = 0x0
    dut.pstrb_i.value = 2 ** (REG_DATA_WIDTH // 8) - 1

    # Ring Oscillator Interface
    dut.rosc_sample_clk_i.value = 0


async def start_dut_clk(dut, clock_period_ns: int) -> None:
    cocotb.start_soon(Clock(dut.clk_i, clock_period_ns, "ns").start())


async def reset_dut(dut) -> None:
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 10)


async def configure_entropy_source(dut):
    pass  # Default values already set in reset


@cocotb.test()
async def csr_access_test(dut):
    """
    CSR Access Test.
    """
    log = logging.getLogger("cocotb.tb")
    clock_period_ns = 1

    await init_entropy_source(dut)
    await start_dut_clk(dut, clock_period_ns)
    await reset_dut(dut)

    log.info("Writing to CTRL register...")
    ctrl_wr = ENTROPY_SOURCE_CTRL_reg_u()
    ctrl_wr.f.module_enable = 0
    await reg_write(dut, CTRL_REG_ADDR, ctrl_wr.val)

    log.info("Reading back from CTRL register...")
    ctrl_rd = ENTROPY_SOURCE_CTRL_reg_u()
    ctrl_rd.val = await reg_read(dut, CTRL_REG_ADDR)
    assert ctrl_rd.val == ctrl_wr.val, "CTRL register read/write mismatch!"
