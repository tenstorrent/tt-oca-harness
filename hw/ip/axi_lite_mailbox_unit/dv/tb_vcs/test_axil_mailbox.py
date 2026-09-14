# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import logging
import os
import random
import sys
from typing import Callable

import cocotb
from cocotb.clock import Clock
from cocotb.regression import TestFactory
from cocotb.triggers import ClockCycles, with_timeout
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

# get register names
sys.path.append(os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))
from axil_mailbox_reg import *

ADDR_WIDTH = 32
DATA_WIDTH = 64

MAILBOX_FIFO_DEPTH = 2
NUM_MAILBOXES = 2
MAILBOX_WIDTH = 64

# Global AXI-Lite master for register access
axil_master = None


async def axil_write(dut, addr: int, data: int, mask=2 ** (DATA_WIDTH // 8) - 1) -> None:
    """Write to AXI-Lite using cocotbext-axi AxiLiteMaster"""
    global axil_master
    await axil_master.write(addr, data.to_bytes(DATA_WIDTH // 8, byteorder="little"))


async def axil_read(dut, addr: int) -> int:
    """Read from AXI-Lite using cocotbext-axi AxiLiteMaster"""
    global axil_master
    read_data = await axil_master.read(addr, DATA_WIDTH // 8)
    return int.from_bytes(read_data.data, byteorder="little")


async def reg_write(dut, addr: int, data: int) -> None:
    """
    Write data to a register at the specified address.
    """
    log = logging.getLogger("cocotb.tb")
    log.info(f"Writing {hex(data)} to register at address {hex(addr)}.")
    await axil_write(dut, addr, data)


async def reg_read(dut, addr: int) -> int:
    """
    Read data from a register at the specified address.
    """
    log = logging.getLogger("cocotb.tb")
    data = await axil_read(dut, addr)
    log.info(f"Read {hex(data)} from register at address {hex(addr)}.")
    return data


async def init_axil_mailbox(dut) -> None:
    """Initialize mailbox DUT signals to safe defaults"""
    # Global Interface
    dut.clk_i.value = 0
    dut.rst_ni.value = 0
    dut.test_en_i.value = 0


async def start_dut_clk(dut, clock_period_ns: int) -> None:
    cocotb.start_soon(Clock(dut.clk_i, clock_period_ns, "ns").start())


async def reset_dut(dut) -> None:
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 10)


async def setup_test(dut, clock_period_ns: int):
    """Setup test environment: initialize, start clock, reset, and create AXI master"""
    global axil_master

    log = logging.getLogger("cocotb.tb")
    log.info("Starting test setup.")

    # Reset signals to safe state
    await init_axil_mailbox(dut)

    # Start clock and reset the DUT
    await start_dut_clk(dut, clock_period_ns)
    await reset_dut(dut)

    # Create AXI-Lite bus using from_prefix
    # The testbench always exposes flattened signals at the top level (no prefix)
    axil_bus = AxiLiteBus.from_prefix(dut, "")

    # Create AXI-Lite master
    axil_master = AxiLiteMaster(axil_bus, dut.clk_i, dut.rst_ni, reset_active_level=False)

    # Allow AXI master to settle after creation
    await ClockCycles(dut.clk_i, 10)

    log.info("Test setup complete.")
    return axil_master


async def write_in_mailbox(dut, num, data):
    full_addr = INBOUND_MAILBOX_0_REG_FILE_BASE_ADDR + num * 0x1000
    await reg_write(dut, full_addr, data)


async def read_in_mailbox(dut, num):
    full_addr = OUTBOUND_MAILBOX_0_REG_FILE_BASE_ADDR + 0x8 + num * 0x1000
    res = await reg_read(dut, full_addr)
    return res


async def write_out_mailbox(dut, num, data):
    full_addr = OUTBOUND_MAILBOX_0_REG_FILE_BASE_ADDR + num * 0x1000
    await reg_write(dut, full_addr, data)


async def read_out_mailbox(dut, num):
    full_addr = INBOUND_MAILBOX_0_REG_FILE_BASE_ADDR + 0x8 + num * 0x1000
    res = await reg_read(dut, full_addr)
    return res


async def mailbox_sanity_test(dut):
    log = logging.getLogger("cocotb.tb")

    # Setup test environment with 10ns clock period
    await setup_test(dut, 10)

    WIRQT = MAILBOX_WIRQT_reg_u()
    WIRQT.f.wirqt = 0x1
    RIRQT = MAILBOX_RIRQT_reg_u()
    RIRQT.f.rirqt = 0x1

    irq_en = MAILBOX_IRQEN_reg_u()
    irq_en.f.wtirq = 1
    irq_en.f.rtirq = 1
    for i in range(NUM_MAILBOXES):
        await reg_write(dut, OUTBOUND_MAILBOX_0_WIRQT_REG_ADDR + (0x1000 * i), WIRQT.val)
        await reg_write(dut, INBOUND_MAILBOX_0_WIRQT_REG_ADDR + (0x1000 * i), WIRQT.val)

        await reg_write(dut, OUTBOUND_MAILBOX_0_RIRQT_REG_ADDR + (0x1000 * i), RIRQT.val)
        await reg_write(dut, INBOUND_MAILBOX_0_RIRQT_REG_ADDR + (0x1000 * i), RIRQT.val)

        # Enable IRQ for inbound mailboxes
        await reg_write(dut, INBOUND_MAILBOX_0_IRQEN_REG_ADDR + (0x1000 * i), irq_en.val)

    log.info("Mailbox IRQs enabled")

    await ClockCycles(dut.clk_i, 16)

    # Generate test data for each mailbox operation, two writes per mailbox.
    test_datas = [
        random.randint(0, 2**MAILBOX_WIDTH - 1)
        for _ in range(NUM_MAILBOXES * MAILBOX_FIFO_DEPTH * 2)
    ]
    n_interrupts = 0

    # Test all inbound mailboxes
    for num in range(NUM_MAILBOXES):
        log.info(f"Testing inbound mailbox {num}")
        await with_timeout(write_in_mailbox(dut, num, test_datas[num * 2]), 1000, "ns")
        await with_timeout(write_in_mailbox(dut, num, test_datas[num * 2 + 1]), 1000, "ns")

        rcvd = await with_timeout(read_in_mailbox(dut, num), 1000, "ns")
        assert rcvd == test_datas[num * 2], (
            f"Test failed for inbound mailbox {num}. Expected {hex(test_datas[num * 2])}, got {hex(rcvd)}"
        )
        rcvd = await with_timeout(read_in_mailbox(dut, num), 1000, "ns")
        assert rcvd == test_datas[num * 2 + 1], (
            f"Test failed for inbound mailbox {num}. Expected {hex(test_datas[num * 2 + 1])}, got {hex(rcvd)}"
        )
        # TODO: check inbound_interrupt_o
        log.info(f"Inbound mailbox {num} test passed")

    # Disable inbound mailbox IRQs
    irq_en = MAILBOX_IRQEN_reg_u()
    irq_en.f.wtirq = 0
    irq_en.f.rtirq = 0
    for i in range(NUM_MAILBOXES):
        await reg_write(dut, INBOUND_MAILBOX_0_IRQEN_REG_ADDR + (0x1000 * i), irq_en.val)

    # Enable outbound mailbox IRQs
    irq_en = MAILBOX_IRQEN_reg_u()
    irq_en.f.wtirq = 1
    irq_en.f.rtirq = 1
    for i in range(NUM_MAILBOXES):
        await reg_write(dut, OUTBOUND_MAILBOX_0_IRQEN_REG_ADDR + (0x1000 * i), irq_en.val)

    # Test all outbound mailboxes, can't trigger an internal interrupt, so we just check the data written and read
    offset = NUM_MAILBOXES * MAILBOX_FIFO_DEPTH  # Offset to start of outbound test data
    for num in range(NUM_MAILBOXES):
        log.info(f"Testing outbound mailbox {num}")
        await with_timeout(write_out_mailbox(dut, num, test_datas[num * 2]), 1000, "ns")
        await with_timeout(write_out_mailbox(dut, num, test_datas[num * 2 + 1]), 1000, "ns")

        rcvd = await with_timeout(read_out_mailbox(dut, num), 1000, "ns")
        assert rcvd == test_datas[num * 2], (
            f"Test failed for outbound mailbox {num}. Expected {hex(test_datas[num * 2])}, got {hex(rcvd)}"
        )
        rcvd = await with_timeout(read_out_mailbox(dut, num), 1000, "ns")
        assert rcvd == test_datas[num * 2 + 1], (
            f"Test failed for outbound mailbox {num}. Expected {hex(test_datas[num * 2 + 1])}, got {hex(rcvd)}"
        )

        # Check outbound_interrupt_o
        if (dut.outbound_interrupt_o.value >> num) & 1 != 1:
            assert False, f"Outbound mailbox {num} did not trigger interrupt"

        log.info(f"Outbound mailbox {num} test passed")

    # TODO: test assert pass/fail


if cocotb.SIM_NAME:
    sanity_tests = [mailbox_sanity_test]
    stress_tests: list[Callable] = []
    tests: list[Callable] = []

    if "+stress" in cocotb.argv:
        tests += sanity_tests
        tests += stress_tests
    else:
        tests += sanity_tests

    for test in tests:
        factory = TestFactory(test)
        factory.generate_tests()
