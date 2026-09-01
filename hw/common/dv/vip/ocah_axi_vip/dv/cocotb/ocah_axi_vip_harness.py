# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the AXI VIP wire-harness selftests.

Two bundles exist in ``tb_top.sv``:

* ``s_axi`` — full stack: ``OcahAxiMasterAgent`` against ``OcahAxiSlaveAgent``
  on the same nets.  Used to prove the blocking result API's response-ID
  observation end to end.
* ``t_axi`` — wire level: this module's request-channel drivers against
  ``OcahAxiSlaveAgent``, so armed response-ID corruption is observable with
  ``OcahAxiIdCapture``.  A cocotbext backend master cannot sit on a corrupted
  bundle: it polices response-ID pairing and fails on an ID it never issued.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_axi_vip import OcahAxiMasterAgent, OcahAxiSlaveAgent

CLK_PERIOD_NS = 4
ID_MASK = 0xFF  # tb_top ID signals are 8 bits wide

log = logging.getLogger("cocotb.tb.ocah_axi_vip_harness")


async def start_clock_reset(dut) -> None:
    """Start the harness clock and run the active-low reset sequence."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)


def build_full_stack(dut, *, timeout_ns: int = 100_000):
    """Attach the shared master and fault-slave agents to the s_axi nets."""
    slave = OcahAxiSlaveAgent.from_prefix(
        dut,
        "s_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_s_axi_slave",
    )
    master = OcahAxiMasterAgent.from_prefix(
        dut,
        "s_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        timeout_ns=timeout_ns,
        name="harness_s_axi_master",
    )
    return master, slave


def build_wire_slave(dut):
    """Attach the fault-slave agent to the t_axi nets and idle the requester side."""
    slave = OcahAxiSlaveAgent.from_prefix(
        dut,
        "t_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_t_axi_slave",
    )
    for name in ("awvalid", "wvalid", "arvalid"):
        getattr(dut, f"t_axi_{name}").value = 0
    for name in (
        "awid",
        "awaddr",
        "awlen",
        "awsize",
        "awburst",
        "awlock",
        "awcache",
        "awprot",
        "awqos",
        "awregion",
        "wdata",
        "wstrb",
        "wlast",
        "arid",
        "araddr",
        "arlen",
        "arsize",
        "arburst",
        "arlock",
        "arcache",
        "arprot",
        "arqos",
        "arregion",
    ):
        getattr(dut, f"t_axi_{name}").value = 0
    dut.t_axi_bready.value = 1
    dut.t_axi_rready.value = 1
    return slave


async def _wait_ready(clock, ready, *, timeout_cycles: int = 200) -> None:
    """Advance to the posedge on which ``ready`` completes the handshake."""
    for _ in range(timeout_cycles):
        await RisingEdge(clock)
        try:
            if int(ready.value) == 1:
                return
        except ValueError:
            continue
    raise AssertionError(f"no ready within {timeout_cycles} cycles on {ready._name}")


async def drive_wire_write(
    dut, *, awid: int, addr: int, data: int, timeout_cycles: int = 200
) -> int:
    """Drive one single-beat AXI write on t_axi by hand; return BRESP.

    The caller observes BID independently (``OcahAxiIdCapture``); this helper
    only completes the request channels and consumes the B handshake.
    """
    clock = dut.clk
    dut.t_axi_awid.value = awid
    dut.t_axi_awaddr.value = addr
    dut.t_axi_awlen.value = 0
    dut.t_axi_awsize.value = 2
    dut.t_axi_awburst.value = 1  # INCR
    dut.t_axi_awvalid.value = 1
    await _wait_ready(clock, dut.t_axi_awready)
    dut.t_axi_awvalid.value = 0

    dut.t_axi_wdata.value = data
    dut.t_axi_wstrb.value = 0xF
    dut.t_axi_wlast.value = 1
    dut.t_axi_wvalid.value = 1
    await _wait_ready(clock, dut.t_axi_wready)
    dut.t_axi_wvalid.value = 0
    dut.t_axi_wlast.value = 0

    for _ in range(timeout_cycles):
        await RisingEdge(clock)
        try:
            if int(dut.t_axi_bvalid.value) == 1 and int(dut.t_axi_bready.value) == 1:
                return int(dut.t_axi_bresp.value)
        except ValueError:
            continue
    raise AssertionError(
        f"no B handshake within {timeout_cycles} cycles for write awid=0x{awid:x} addr=0x{addr:08x}"
    )


async def drive_wire_read(
    dut, *, arid: int, addr: int, timeout_cycles: int = 200
) -> tuple[int, int]:
    """Drive one single-beat AXI read on t_axi by hand; return (RRESP, RDATA).

    The caller observes RID independently (``OcahAxiIdCapture``); this helper
    only completes the AR channel and consumes the R handshake.
    """
    clock = dut.clk
    dut.t_axi_arid.value = arid
    dut.t_axi_araddr.value = addr
    dut.t_axi_arlen.value = 0
    dut.t_axi_arsize.value = 2
    dut.t_axi_arburst.value = 1  # INCR
    dut.t_axi_arvalid.value = 1
    await _wait_ready(clock, dut.t_axi_arready)
    dut.t_axi_arvalid.value = 0

    for _ in range(timeout_cycles):
        await RisingEdge(clock)
        try:
            if int(dut.t_axi_rvalid.value) == 1 and int(dut.t_axi_rready.value) == 1:
                return int(dut.t_axi_rresp.value), int(dut.t_axi_rdata.value)
        except ValueError:
            continue
    raise AssertionError(
        f"no R handshake within {timeout_cycles} cycles for read arid=0x{arid:x} addr=0x{addr:08x}"
    )
