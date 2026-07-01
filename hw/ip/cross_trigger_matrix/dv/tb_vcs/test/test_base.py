# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Base test utilities for Cross Trigger Matrix testbench
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
    from cross_trigger_matrix_reg import (
        CROSS_TRIGGER_MATRIX_CT_SRC0_CONFIG_REG_DEFAULT,
        CROSS_TRIGGER_MATRIX_CT_SRC1_CONFIG_REG_DEFAULT,
        CROSS_TRIGGER_MATRIX_CT_SRC2_CONFIG_REG_DEFAULT,
        CROSS_TRIGGER_MATRIX_CT_SRC3_CONFIG_REG_DEFAULT,
    )
except ImportError:
    # Fallback if registers not generated yet
    CROSS_TRIGGER_MATRIX_CT_SRC0_CONFIG_REG_DEFAULT = 0x0
    CROSS_TRIGGER_MATRIX_CT_SRC1_CONFIG_REG_DEFAULT = 0x0
    CROSS_TRIGGER_MATRIX_CT_SRC2_CONFIG_REG_DEFAULT = 0x0
    CROSS_TRIGGER_MATRIX_CT_SRC3_CONFIG_REG_DEFAULT = 0x0

# Register Address Map (CT_SRC[i]_CONFIG registers)
REG_MAP = {
    'CT_SRC0_CONFIG':  (0x0,  'RW', 'CT_Src[0] Configuration', CROSS_TRIGGER_MATRIX_CT_SRC0_CONFIG_REG_DEFAULT, 0xFFFFFFFF),
    'CT_SRC1_CONFIG':  (0x4,  'RW', 'CT_Src[1] Configuration', CROSS_TRIGGER_MATRIX_CT_SRC1_CONFIG_REG_DEFAULT, 0xFFFFFFFF),
    'CT_SRC2_CONFIG':  (0x8,  'RW', 'CT_Src[2] Configuration', CROSS_TRIGGER_MATRIX_CT_SRC2_CONFIG_REG_DEFAULT, 0xFFFFFFFF),
    'CT_SRC3_CONFIG':  (0xC,  'RW', 'CT_Src[3] Configuration', CROSS_TRIGGER_MATRIX_CT_SRC3_CONFIG_REG_DEFAULT, 0xFFFFFFFF),
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

async def write_ct_src_config(dut, axil, src_idx, select_mask):
    """Write CT_SRC[i]_CONFIG register with select mask"""
    addr = src_idx * 4
    await axil_write(dut, axil, addr, select_mask)

async def read_ct_src_config(dut, axil, src_idx):
    """Read CT_SRC[i]_CONFIG register"""
    addr = src_idx * 4
    return await axil_read(dut, axil, addr)

async def pulse_ct_dst(dut, dst_idx, duration_cycles=1):
    """Generate pulse on CT_Dst[dst_idx]"""
    dut.ct_dst.value = 1 << dst_idx
    for _ in range(duration_cycles):
        await RisingEdge(dut.clk)
    dut.ct_dst.value = 0

async def wait_for_ct_src_pulse(dut, src_idx, timeout_cycles=1000):
    """Wait for pulse on CT_Src[src_idx]"""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if (dut.ct_src.value >> src_idx) & 1 == 1:
            return True
    return False

async def check_ct_src_low(dut, src_idx, cycles=10):
    """Check that CT_Src[src_idx] remains low for specified cycles"""
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        if (dut.ct_src.value >> src_idx) & 1 == 1:
            return False
    return True
