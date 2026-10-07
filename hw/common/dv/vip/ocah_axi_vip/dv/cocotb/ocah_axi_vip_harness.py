# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the AXI VIP wire-harness selftests.

Three bundles exist in ``tb_top.sv``:

* ``s_axi`` — full stack: ``OcahAxiMasterAgent`` against ``OcahAxiSlaveAgent``
  on the same nets.  Used to prove the blocking result API's response-ID
  observation end to end.
* ``t_axi`` — wire level: this module's request-channel drivers against
  ``OcahAxiSlaveAgent``, so armed response-ID corruption is observable with
  ``OcahAxiIdCapture``.  A cocotbext backend master cannot sit on a corrupted
  bundle: it polices response-ID pairing and fails on an ID it never issued.
* ``l_axi`` — AXI4-Lite stack: ``OcahAxiLiteMasterAgent`` against
  ``OcahAxiLiteSlaveAgent``, for the lite protocol-control selftests
  (AW/W launch skew, deferred BREADY/RREADY, partial strobes) with every
  handshake observable at the flat nets.
* ``u_wide_axi_if`` / ``u_wide_axil_if`` — default-geometry ``ocah_axi_if``
  instances (64-bit address and data, 16-bit ID and user). The geometry
  selftests bind the 32-bit stacks to them through ``OcahAxiConfig`` and
  judge the member bits above the configured geometry at the raw handles.
* ``mt_axi`` / ``u_mt_axi_if`` — the struct-port bundle: ``OcahAxiMasterAgent``
  drives the flat request nets that tb_top packs into a pulp request struct,
  ``ocah_axi_struct_bridge`` places that struct on ``u_mt_axi_if``, and
  ``OcahAxiSlaveAgent`` answers there with ``OcahAxiMonitor`` feeding the VIP
  scoreboard, the topology a block tb_top uses for a struct boundary.

The seed accessor and the salted scenario RNG live here: these selftests are
plain cocotb tests without a base test class.
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_axi_vip import (
    OcahAxiConfig,
    OcahAxiLiteMasterAgent,
    OcahAxiLiteSlaveAgent,
    OcahAxiMasterAgent,
    OcahAxiMonitor,
    OcahAxiProtocol,
    OcahAxiSlaveAgent,
)
from ocah_lib import OcahRng

CLK_PERIOD_NS = 4
ID_MASK = 0xFF  # tb_top ID signals are 8 bits wide
_SEED_ENV = "RANDOM_SEED"

# Real bus geometry the geometry selftests bind onto the default-geometry
# ocah_axi_if instances (whose members are 64/64-bit with 16-bit ID and user).
WIDE_LITE_GEOMETRY = OcahAxiConfig(protocol=OcahAxiProtocol.AXI4_LITE, addr_width=32, data_width=32)
WIDE_AXI_GEOMETRY = OcahAxiConfig(
    protocol=OcahAxiProtocol.AXI4, addr_width=32, data_width=32, id_width=8, user_width=1
)

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


def build_lite_stack(dut, *, timeout_ns: int = 100_000):
    """Attach the shared lite master and lite RAM slave agents to the l_axi nets."""
    slave = OcahAxiLiteSlaveAgent.from_prefix(
        dut,
        "l_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_l_axi_slave",
    )
    master = OcahAxiLiteMasterAgent.from_prefix(
        dut,
        "l_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        timeout_ns=timeout_ns,
        name="harness_l_axi_master",
    )
    return master, slave


def base_seed() -> int:
    """Runner-provided seed; the harness's one read of the seed variable."""
    return int(os.environ.get(_SEED_ENV, "1"), 0)


def scenario_rng(label: str) -> random.Random:
    """Seeded stream for one scenario, salted by ``label``."""
    return random.Random(OcahRng.salted_seed(base_seed(), label))


def build_wide_lite_stack(
    dut: Any, *, timeout_ns: int = 100_000
) -> tuple[OcahAxiLiteMasterAgent, OcahAxiLiteSlaveAgent]:
    """Attach the lite master and lite RAM slave to u_wide_axil_if at 32-bit geometry."""
    scope = dut.u_wide_axil_if
    slave = OcahAxiLiteSlaveAgent(
        WIDE_LITE_GEOMETRY.bus(scope),
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_wide_axil_slave",
    )
    master = OcahAxiLiteMasterAgent(
        WIDE_LITE_GEOMETRY.bus(scope),
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        timeout_ns=timeout_ns,
        name="harness_wide_axil_master",
    )
    return master, slave


def build_wide_full_stack(
    dut: Any, *, timeout_ns: int = 100_000
) -> tuple[OcahAxiMasterAgent, OcahAxiSlaveAgent]:
    """Attach the AXI4 master and RAM slave to u_wide_axi_if at 32-bit, 8-bit-ID geometry."""
    scope = dut.u_wide_axi_if
    slave = OcahAxiSlaveAgent(
        WIDE_AXI_GEOMETRY.bus(scope),
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_wide_axi_slave",
    )
    master = OcahAxiMasterAgent(
        WIDE_AXI_GEOMETRY.bus(scope),
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        timeout_ns=timeout_ns,
        name="harness_wide_axi_master",
    )
    return master, slave


def upper_lanes(handle: Any, width: int) -> int | None:
    """Value of the bits of ``handle`` above bit ``width``; ``None`` when any of them is X or Z."""
    bits = str(handle.value)[:-width]
    if not bits:
        return 0
    try:
        return int(bits, 2)
    except ValueError:
        return None


def build_wire_slave(dut, *, max_outstanding: int | None = None):
    """Attach the fault-slave agent to the t_axi nets and idle the requester side."""
    slave = OcahAxiSlaveAgent.from_prefix(
        dut,
        "t_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_t_axi_slave",
        max_outstanding=max_outstanding,
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


def _sample(handle) -> int:
    """Sample a signal as an int; X resolves to 0."""
    try:
        return int(handle.value)
    except ValueError:
        return 0


_LITE_WRITE_KEYS = (
    "awvalid",
    "awready",
    "awaddr",
    "wvalid",
    "wready",
    "wdata",
    "wstrb",
    "bvalid",
    "bready",
)
_LITE_READ_KEYS = ("arvalid", "arready", "araddr", "rvalid", "rready", "rdata", "rresp")


async def observe_lite_write(
    dut, *, max_cycles: int = 400, handshakes: int = 1
) -> list[dict[str, int]]:
    """Record the l_axi write channels once per cycle until the ``handshakes``-th B handshake.

    Start as a background task before issuing the transaction; the returned
    per-cycle sample list is the wire-level truth the tests judge the VIP's
    skew/deferral claims against (independent of the VIP's own bookkeeping).
    """
    samples: list[dict[str, int]] = []
    seen = 0
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        row = {key: _sample(getattr(dut, f"l_axi_{key}")) for key in _LITE_WRITE_KEYS}
        samples.append(row)
        if row["bvalid"] and row["bready"]:
            seen += 1
            if seen >= handshakes:
                return samples
    raise AssertionError(f"no {handshakes} l_axi B handshake(s) within {max_cycles} cycles")


async def observe_lite_read(
    dut, *, max_cycles: int = 400, handshakes: int = 1
) -> list[dict[str, int]]:
    """Record the l_axi read channels once per cycle until the ``handshakes``-th R handshake."""
    samples: list[dict[str, int]] = []
    seen = 0
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        row = {key: _sample(getattr(dut, f"l_axi_{key}")) for key in _LITE_READ_KEYS}
        samples.append(row)
        if row["rvalid"] and row["rready"]:
            seen += 1
            if seen >= handshakes:
                return samples
    raise AssertionError(f"no {handshakes} l_axi R handshake(s) within {max_cycles} cycles")


def stall_cycles(samples: list[dict[str, int]], valid: str, ready: str) -> int:
    """Number of sampled cycles with ``valid`` set and ``ready`` clear."""
    return sum(1 for row in samples if row[valid] and not row[ready])


def handshake_cycles(samples: list[dict[str, int]], valid: str, ready: str) -> list[int]:
    """Every sample index where ``valid`` and ``ready`` are both set, in order."""
    return [index for index, row in enumerate(samples) if row[valid] and row[ready]]


def address_stable_while_stalled(
    samples: list[dict[str, int]], valid: str, ready: str, addr: str
) -> bool:
    """True when every stalled beat kept ``valid`` set and ``addr`` unchanged until ``ready``."""
    pending: int | None = None
    for row in samples:
        if row[valid] and pending is not None and row[addr] != pending:
            return False
        if row[valid] and not row[ready]:
            pending = row[addr]
        elif row[valid] and row[ready]:
            pending = None
        elif pending is not None:
            return False
    return True


def first_cycle(samples: list[dict[str, int]], key: str, *, start: int = 0) -> int | None:
    """Return the first sample index at or after ``start`` where ``key`` is set."""
    for index in range(start, len(samples)):
        if samples[index][key]:
            return index
    return None


def handshake_cycle(samples: list[dict[str, int]], valid: str, ready: str) -> int | None:
    """Return the first sample index where ``valid`` and ``ready`` are both set."""
    for index, row in enumerate(samples):
        if row[valid] and row[ready]:
            return index
    return None


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
    dut, *, awid: int, addr: int, data: int, w_first: bool = False, timeout_cycles: int = 200
) -> int:
    """Drive one single-beat AXI write on t_axi by hand; return BRESP.

    The caller observes BID independently (``OcahAxiIdCapture``); this helper
    only completes the request channels and consumes the B handshake.
    ``w_first`` completes the W handshake before AWVALID rises.
    """
    clock = dut.clk

    async def address() -> None:
        dut.t_axi_awid.value = awid
        dut.t_axi_awaddr.value = addr
        dut.t_axi_awlen.value = 0
        dut.t_axi_awsize.value = 2
        dut.t_axi_awburst.value = 1  # INCR
        dut.t_axi_awvalid.value = 1
        await _wait_ready(clock, dut.t_axi_awready)
        dut.t_axi_awvalid.value = 0

    async def data_beat() -> None:
        dut.t_axi_wdata.value = data
        dut.t_axi_wstrb.value = 0xF
        dut.t_axi_wlast.value = 1
        dut.t_axi_wvalid.value = 1
        await _wait_ready(clock, dut.t_axi_wready)
        dut.t_axi_wvalid.value = 0
        dut.t_axi_wlast.value = 0

    for phase in (data_beat, address) if w_first else (address, data_beat):
        await phase()

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


async def drive_wire_ar(dut, *, arid: int, addr: int) -> None:
    """Complete one single-beat AR handshake on t_axi by hand."""
    dut.t_axi_arid.value = arid
    dut.t_axi_araddr.value = addr
    dut.t_axi_arlen.value = 0
    dut.t_axi_arsize.value = 2
    dut.t_axi_arburst.value = 1  # INCR
    dut.t_axi_arvalid.value = 1
    await _wait_ready(dut.clk, dut.t_axi_arready)
    dut.t_axi_arvalid.value = 0


async def drive_wire_read(
    dut, *, arid: int, addr: int, timeout_cycles: int = 200
) -> tuple[int, int]:
    """Drive one single-beat AXI read on t_axi by hand; return (RRESP, RDATA).

    The caller observes RID independently (``OcahAxiIdCapture``); this helper
    only completes the AR channel and consumes the R handshake.
    """
    clock = dut.clk
    await drive_wire_ar(dut, arid=arid, addr=addr)

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


def build_bridge_stack(
    dut: Any, *, timeout_ns: int = 100_000
) -> tuple[OcahAxiMasterAgent, OcahAxiSlaveAgent, OcahAxiMonitor]:
    """Master on the mt_axi struct-side nets; slave agent and monitor on u_mt_axi_if.

    The struct geometry (32-bit address and data, 8-bit ID, 1-bit user) is the
    one ``WIDE_AXI_GEOMETRY`` binds onto the default-geometry interface.
    """
    scope = dut.u_mt_axi_if
    slave = OcahAxiSlaveAgent(
        WIDE_AXI_GEOMETRY.bus(scope),
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        size=2**16,
        name="harness_mt_axi_slave",
    )
    monitor = OcahAxiMonitor(WIDE_AXI_GEOMETRY.bus(scope), dut.clk, name="harness_mt_axi_monitor")
    master = OcahAxiMasterAgent.from_prefix(
        dut,
        "mt_axi",
        dut.clk,
        dut.rst_n,
        reset_active_level=False,
        timeout_ns=timeout_ns,
        name="harness_mt_axi_master",
    )
    return master, slave, monitor
