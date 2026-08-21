# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
Base test utilities for Cross Trigger Network testbench

Committed source. Upstream expanded this file from the same template as
cross_trigger_network_pkg.sv; that generator was not carried into this tree, so
the port counts below are edited by hand and must match the package.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ReadOnly
from typing import Optional
import sys
from pathlib import Path

# Import AXI-Lite VIP from CTP testbench. The cross_trigger IPs are siblings
# under hw/ip/cross_trigger/, each with its testbench under dv/, so walk up to
# that shared parent rather than to hw/.
sys.path.insert(0, str(Path(__file__).parents[4] / 'cross_trigger_port' / 'dv' / 'tb_vcs' / 'axil_vip'))
from axil_master import AxiLiteMaster

# Port counts, which must match cross_trigger_network_pkg
NUM_CTP = 16
NUM_INT_CT = 10
NUM_CTM_PORTS = NUM_CTP + NUM_INT_CT

# Internal CTP mode configuration:
# Lower half (indices 0 to NUM_INT_CT_WIRE_OR-1) = Wire-OR mode
# Upper half (indices NUM_INT_CT_WIRE_OR to NUM_INT_CT-1) = P2P mode
NUM_INT_CT_WIRE_OR = NUM_INT_CT // 2
NUM_INT_CT_P2P = NUM_INT_CT - NUM_INT_CT_WIRE_OR


def is_internal_ct_wire_or(int_ct_idx: int) -> bool:
    """Check if internal CT at given index is in Wire-OR mode"""
    return int_ct_idx < NUM_INT_CT_WIRE_OR


def is_internal_ct_p2p(int_ct_idx: int) -> bool:
    """Check if internal CT at given index is in P2P mode"""
    return int_ct_idx >= NUM_INT_CT_WIRE_OR

# Address space configuration
ADDR_CTM_SIZE = 0x200  # 512 bytes for CTM (enough for up to 64 CT_SRC register pairs, 8 bytes each)
ADDR_CTP_SIZE = 0x10   # 16 bytes per CTP (enough for 3 registers)
CTM_BASE_ADDR = 0x0000  # CTM is always at base address
CTP_BASE_ADDR = 0x0200  # CTPs start after CTM (at 0x200)

# CTP Register offsets (within each CTP's 16-byte block)
CTP_REG_CONFIG       = 0x0
CTP_REG_STATUS       = 0x4
CTP_REG_STRETCH_MULT = 0x8


def get_ctp_addr(ctp_idx: int, reg_offset: int) -> int:
    """Calculate address for CTP register (CTPs start at 0x0200)"""
    if ctp_idx >= NUM_CTP:
        raise ValueError(f"CTP index {ctp_idx} out of range (0-{NUM_CTP-1})")
    return CTP_BASE_ADDR + (ctp_idx * ADDR_CTP_SIZE) + reg_offset


def get_ctm_addr(reg_offset: int) -> int:
    """Calculate address for CTM register (CTM is at 0x0000)"""
    return CTM_BASE_ADDR + reg_offset


def get_ctm_src_config_addr(src_idx: int, reg_idx: int = 0) -> int:
    """Calculate address for CTM CT_SRCn_CONFIG register

    Args:
        src_idx: CT_SRC index (0 to NUM_CTM_PORTS-1)
        reg_idx: Register index (0 for CONFIG_0, 1 for CONFIG_1)

    Returns:
        Address of the specified CTM register

    Note:
        Each CT_SRC uses 8 bytes (CONFIG_0 at offset 0, CONFIG_1 at offset 4)
        CONFIG_0 handles CT_Dst[31:0], CONFIG_1 handles CT_Dst[63:32]
    """
    if src_idx >= NUM_CTM_PORTS:
        raise ValueError(f"CTM source index {src_idx} out of range (0-{NUM_CTM_PORTS-1})")
    if reg_idx not in (0, 1):
        raise ValueError(f"Register index {reg_idx} must be 0 (CONFIG_0) or 1 (CONFIG_1)")
    return CTM_BASE_ADDR + (src_idx * 8) + (reg_idx * 4)


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


async def wait_cycles(dut, n):
    """Wait for n clock cycles"""
    for _ in range(n):
        await RisingEdge(dut.clk)


async def wait_for_signal(dut, signal, value=1, timeout_cycles=1000):
    """Wait for signal to reach specified value"""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if int(signal.value) == value:
            return True
    return False
