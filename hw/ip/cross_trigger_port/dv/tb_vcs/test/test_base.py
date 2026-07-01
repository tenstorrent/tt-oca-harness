# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Base test utilities for Cross Trigger Port testbench
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
from typing import Optional
import sys
from pathlib import Path

# Import AXI-Lite VIP
sys.path.insert(0, str(Path(__file__).parent.parent / 'axil_vip'))
from axil_master import AxiLiteMaster

# Import register definitions
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'data' / 'registers' / 'py_headers'))
try:
    from cross_trigger_port_reg import (
        CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT,
        CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT,
        CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT,
    )
except ImportError:
    # Fallback if registers not generated yet
    CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT = 0x0
    CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT = 0x0
    CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT = 0x0

# Register Address Map
REG_MAP = {
    'CONFIG':      (0x0, 'RW', 'Configuration', CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT, 0x7),
    'STATUS':      (0x4, 'RO', 'Status', CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT, 0x0),
    'STRETCH_MULT': (0x8, 'RW', 'Pulse Stretch Multiplier', CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT, 0xFFFF),
}

async def start_clocks(dut, period_ns=10):
    """Start clock generation"""
    clock = Clock(dut.clk, period_ns, units="ns")
    cocotb.start_soon(clock.start())
    return clock

async def init(dut):
    """Initialize DUT"""
    dut.rst_n.value = 0
    await Timer(100, units="ns")
    dut.rst_n.value = 1
    await Timer(100, units="ns")

async def init_axil(dut):
    """Initialize AXI-Lite signals"""
    # Initialize flattened AXI-Lite signals
    dut.axil_awvalid.value = 0
    dut.axil_wvalid.value = 0
    dut.axil_bready.value = 0
    dut.axil_arvalid.value = 0
    dut.axil_rready.value = 0
    dut.axil_awaddr.value = 0
    dut.axil_awprot.value = 0
    dut.axil_wdata.value = 0
    dut.axil_wstrb.value = 0
    dut.axil_araddr.value = 0
    dut.axil_arprot.value = 0

async def axil_write(dut, axil, addr, data):
    """Write to AXI-Lite register"""
    await axil.write(addr, data)

async def axil_read(dut, axil, addr):
    """Read from AXI-Lite register"""
    return await axil.read(addr)

async def reg_write(dut, axil, reg_name, value):
    """Write to named register"""
    addr, _, _, _, _ = REG_MAP[reg_name]
    await axil_write(dut, axil, addr, value)

async def reg_read(dut, axil, reg_name):
    """Read named register"""
    addr, _, _, _, _ = REG_MAP[reg_name]
    return await axil_read(dut, axil, addr)

async def wait_for_busy_clear(dut, timeout_cycles=1000):
    """Wait for BUSY bit to clear"""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if dut.u_dut.busy_o.value == 0:
            return True
    return False

async def wait_for_pulse(dut, signal, timeout_cycles=1000):
    """Wait for pulse on signal"""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if signal.value == 1:
            return True
    return False
