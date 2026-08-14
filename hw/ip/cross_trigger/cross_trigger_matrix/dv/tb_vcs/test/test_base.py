# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Base test utilities for Cross Trigger Matrix testbench
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
from typing import Optional
import re
import sys
from pathlib import Path

# Import AXI-Lite VIP
sys.path.insert(0, str(Path(__file__).parent.parent / 'axil_vip'))
from axil_master import AxiLiteMaster

# Import register definitions from the generated Python header
sys.path.insert(0, str(Path(__file__).parents[3] / 'regs' / 'gen' / 'py'))
import cross_trigger_matrix_reg as ctm_regs

# The header declares one CONFIG_0 constant per CT_Src port, so counting them
# tracks whatever port count the register map was generated for
NUM_CT_SRC = sum(
    1 for name in dir(ctm_regs)
    if re.fullmatch(r'CT_SRC_\d+__CONFIG_0_REG_ADDR', name)
)

# Bits above the select field are unmapped: they read as zero however they are
# written, so readback checks compare against this mask. Width comes from the
# generated ctypes bitfield rather than being restated here.
NUM_CT_DST = dict(
    (name, width) for name, _, width in ctm_regs.CT_SRC_CONFIG_0_reg_t._fields_
)['ct_dst_select']
CT_DST_SELECT_MASK = (1 << NUM_CT_DST) - 1

def ct_src_config_addr(src_idx):
    """Address of the CT_Src[src_idx] config register, from the generated header"""
    return getattr(ctm_regs, f'CT_SRC_{src_idx}__CONFIG_0_REG_ADDR')

# One config register per CT_Src port, addressed from the generated header so the
# stride never has to be restated here
REG_MAP = {
    f'CT_SRC{i}_CONFIG_0': (
        ct_src_config_addr(i),
        'RW',
        f'CT_Src[{i}] Configuration',
        ctm_regs.CT_SRC_CONFIG_0_REG_DEFAULT,
        CT_DST_SELECT_MASK,
    )
    for i in range(NUM_CT_SRC)
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
    await axil_write(dut, axil, ct_src_config_addr(src_idx), select_mask)

async def read_ct_src_config(dut, axil, src_idx):
    """Read CT_SRC[i]_CONFIG register"""
    return await axil_read(dut, axil, ct_src_config_addr(src_idx))

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
