# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the Cross Trigger Network IP-level cocotb tests.

The bench drives four surfaces of ``cross_trigger_network_tb_top``:

* the AXI4-Lite CSR crossbar through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only) — CTM registers at 0x000, per-CTP
  registers at 0x200 + i*0x10 (cross_trigger_network_pkg address map);
* the external CTP GPIO pad pins (packed ``ctp_*`` vectors, one bit per CTP).
  Each CT_Req_out pad sits on an open-drain shared wire of ``tb_top``:
  ``ctp_wire_pull`` is the level each private wire rests at,
  ``ctp_wire_ext_assert`` the bench-side chiplet pulling a wire,
  ``ctp_wire_group`` the pads that share one wire (resting at
  ``ctp_wire_group_pull``), and ``ctp_req_out_din`` the resolved wires the
  pads present to the ports;
* the internal CT port pins (``ctm_dst_req``/``ctm_src_ack`` inputs,
  ``ctm_src_req``/``ctm_dst_ack`` outputs);
* the clock-stop pins (``clk_stop_req``/``jtag_clock_stop`` inputs,
  ``stop_clks``/``cla_clock_stop`` outputs).

Register offsets inside each endpoint window come from the generated RDL
headers of the embedded IPs (cross_trigger_matrix_reg, cross_trigger_port_reg);
the network geometry constants mirror cross_trigger_network_pkg.sv, which is
hand-maintained (no generated collateral exists for the network level).

Packed input vectors are driven through shadow values (`set_input_bit`) so
individual bits can be flipped without read-modify-write races on the
simulator handle.

Wire-OR polarity follows CONFIG.INVERT (``WIRE_OR_POLARITY``): INVERT=0 is an
active-low wire with a pull-up, INVERT=1 an active-high wire with a
pull-down. A port receives a trigger when its synchronized wire moves from
rest to asserted, ``CT_DST_LATENCY`` clocks after the edge; the CLA request of
an internal wire-OR port is active-high and delivers on its rising edge.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import cocotb
import cross_trigger_matrix_reg as _ctm_reg
import cross_trigger_port_reg as _ctp_reg
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import OcahAxiLiteMasterAgent

CLK_PERIOD_NS = 10

# Network geometry: keep in step with cross_trigger_network_pkg.sv.
NUM_CTP = 16
NUM_INT_CT = 10
NUM_CLK_STOP_REQ = 9
NUM_CTM_PORTS = NUM_CTP + NUM_INT_CT

# Internal CT mode split programmed by tb_top.sv's IntCtMode parameter:
# lower half wire-OR (pulse), upper half point-to-point (handshake).
NUM_INT_CT_WIRE_OR = NUM_INT_CT // 2

# CSR address map: CTM window first, then one window per external CTP
# (cross_trigger_network_pkg CSR_ADDR_CTM_SIZE / CSR_ADDR_CTP_SIZE).
CTM_BASE_ADDR = 0x000
CTM_REG_END = CTM_BASE_ADDR + _ctm_reg.CROSS_TRIGGER_MATRIX_REG_MAP_SIZE  # first address past it
CTP_BASE_ADDR = 0x200
CTP_STRIDE = 0x10
UNMAPPED_ADDR = CTP_BASE_ADDR + NUM_CTP * CTP_STRIDE  # first address past the map

# Endpoint-internal register offsets from the embedded IPs' generated headers.
CTP_CONFIG_OFFSET = _ctp_reg.CONFIG_REG_OFFSET
CTP_STATUS_OFFSET = _ctp_reg.STATUS_REG_OFFSET
CTP_STRETCH_OFFSET = _ctp_reg.STRETCH_MULT_REG_OFFSET
CTM_SELECT_MASK = (1 << NUM_CTM_PORTS) - 1
CTP_STATUS_BUSY_BIT = 0

# Bounded worst-case end-to-end latency in clk cycles for one network hop:
# CTP input 2-FF sync + edge detect + ct_dst register + CTM output register
# + CTP stretcher/handshake FSM + pad output register.
E2E_LATENCY = 12

# External CTP stretch programmed by the tests' wire-OR setup; the internal
# wire-OR CT ports use the RTL's fixed stretch of 1 (2-cycle pulses).
EXT_WIRE_OR_STRETCH = 4
INT_WIRE_OR_STRETCH = 1

# Clock edges from the edge at which a wire-OR receive input moves to the
# edge at which that port's ct_dst is high: the two synchronizer stages and
# the registered ct_dst output.
CT_DST_LATENCY = 3

# Cycles a source holds its wire or its CLA request. At least the end-to-end
# bound, so a receiver that fires on the release edge misses every delivery
# window judged against E2E_LATENCY.
SOURCE_HOLD_CYCLES = E2E_LATENCY


@dataclass(frozen=True)
class WirePolarity:
    """Rest and asserted levels of a shared wire for one INVERT sense."""

    pull: int
    assert_level: int


# CONFIG.INVERT -> shared-wire polarity in wire-OR mode (cross_trigger_port.rdl):
# INVERT=0 is active-low with a pull-up, INVERT=1 active-high with a pull-down.
WIRE_OR_POLARITY = {
    0: WirePolarity(pull=1, assert_level=0),
    1: WirePolarity(pull=0, assert_level=1),
}

# Packed DUT input vectors the bench drives as stimulus, all quiescent at 0:
# no chiplet pulling, no shared group, request and acknowledge pads low.
DRIVEN_INPUTS = (
    "ctp_wire_ext_assert",
    "ctp_wire_group",
    "ctp_req_in_din",
    "ctp_ack_in_din",
    "ctp_ack_out_din",
    "ctm_dst_req",
    "ctm_src_ack",
    "clk_stop_req",
)

# Packed DUT input vectors that describe the board: the pull of every private
# wire, all pull-ups for the reset-default INVERT=0.
BOARD_INPUTS = ("ctp_wire_pull",)


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def ctm_src_cfg_addr(matrix_port: int) -> int:
    """CSR address of the CTM select register for one matrix output port."""
    return CTM_BASE_ADDR + getattr(_ctm_reg, f"CT_SRC_{matrix_port}__CONFIG_0_REG_ADDR")


def ctp_addr(ctp_index: int, offset: int) -> int:
    """CSR address of one register inside an external CTP's window."""
    return CTP_BASE_ADDR + ctp_index * CTP_STRIDE + offset


def int_ct_matrix_port(int_ct_index: int) -> int:
    """Matrix port number of an internal CT (they follow the external CTPs)."""
    return NUM_CTP + int_ct_index


def is_int_ct_wire_or(int_ct_index: int) -> bool:
    return int_ct_index < NUM_INT_CT_WIRE_OR


def current_cycle() -> int:
    """Index of the current clock cycle, counted from the first rising edge.

    Derived from simulation time so every coroutine, whichever edge it woke
    on, agrees on the index of the cycle it is in.
    """
    return int(get_sim_time("ns") // CLK_PERIOD_NS)


class CtnTb:
    """Clock/reset bring-up, CSR access, and pin-level helpers."""

    def __init__(self, dut, name: str = "ctn_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self._shadow = dict.fromkeys(DRIVEN_INPUTS + BOARD_INPUTS, 0)

    async def start(self) -> None:
        """Init inputs, start the clock, run reset, and bring up the VIP.

        Every private wire rests at the pull-up of the reset-default sense
        (INVERT=0), and so does the group wire.
        """
        dut = self.dut
        for name in DRIVEN_INPUTS:
            self.set_input(name, 0)
        self.set_input("ctp_wire_pull", (1 << NUM_CTP) - 1)
        dut.ctp_wire_group_pull.value = WIRE_OR_POLARITY[0].pull
        dut.jtag_clock_stop.value = 0
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="ctn_axil_host",
            timeout_cycles=1000,
        )
        self.seq = self.agent.sequence
        await self.agent.start()

        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 5)
        self.log.info(
            "bring-up complete: %d external CTPs, %d internal CTs (%d wire-OR + %d P2P)",
            NUM_CTP,
            NUM_INT_CT,
            NUM_INT_CT_WIRE_OR,
            NUM_INT_CT - NUM_INT_CT_WIRE_OR,
        )

    # ------------------------------------------------------------------
    # CSR access
    # ------------------------------------------------------------------

    async def route(self, target_port: int, source_mask: int) -> None:
        """Program one CTM output port's select mask (0 disconnects it)."""
        self.log.info("route: matrix port %d selects mask 0x%07x", target_port, source_mask)
        await self.seq.write(ctm_src_cfg_addr(target_port), source_mask)

    async def config_ctp(
        self, index: int, mode: int, invert: int = 0, stretch: int | None = None
    ) -> None:
        """Program one external CTP's CONFIG (and STRETCH_MULT for wire-OR).

        The CTP core's sender handshake FSM latches ct_src pulses in BOTH
        modes (only the pad muxing is mode-dependent), and wire-OR traffic
        never acks it — so a port that carried wire-OR traffic and is later
        reconfigured to P2P would surface a stale request. CONFIG.RESET is
        the spec's recovery knob for exactly this; pulse it on every mode
        (re)configuration so each scenario starts from an idle FSM.
        """
        value = (mode & 1) | ((invert & 1) << 1)
        if mode == 0:
            self.set_wire_pull(index, invert)
        await self.seq.write(ctp_addr(index, CTP_CONFIG_OFFSET), value | (1 << 2))
        await self.seq.write(ctp_addr(index, CTP_CONFIG_OFFSET), value)
        if stretch is not None:
            await self.seq.write(ctp_addr(index, CTP_STRETCH_OFFSET), stretch)
        self.log.info(
            "CTP[%d]: MODE=%s INVERT=%d%s",
            index,
            "P2P" if mode else "wire-OR",
            invert,
            "" if stretch is None else f" STRETCH_MULT={stretch}",
        )

    async def read_ctp_status(self, index: int) -> int:
        return await self.seq.read(ctp_addr(index, CTP_STATUS_OFFSET))

    # ------------------------------------------------------------------
    # Pin-level stimulus and observation
    # ------------------------------------------------------------------

    def set_input(self, name: str, value: int) -> None:
        self._shadow[name] = value
        getattr(self.dut, name).value = value

    def set_input_bit(self, name: str, bit: int, level: int) -> None:
        value = self._shadow[name]
        value = (value | (1 << bit)) if level else (value & ~(1 << bit))
        self.set_input(name, value)

    async def pulse_input_bit(self, name: str, bit: int, cycles: int) -> int:
        """Assert one packed-input bit for ``cycles`` clocks, then clear it.

        Returns the cycle in which the bit rose. External and internal CTP
        inputs pass 2-FF synchronizers, so hold pulses for at least 3 cycles
        to guarantee capture.
        """
        await RisingEdge(self.dut.clk)
        self.set_input_bit(name, bit, 1)
        start = current_cycle()
        await ClockCycles(self.dut.clk, cycles)
        self.set_input_bit(name, bit, 0)
        return start

    # ------------------------------------------------------------------
    # Shared-wire board and chiplets
    # ------------------------------------------------------------------

    def set_wire_pull(self, index: int, invert: int) -> None:
        """Rest CTP ``index``'s private wire at the pull of the board built for ``invert``."""
        self.set_input_bit("ctp_wire_pull", index, WIRE_OR_POLARITY[invert].pull)

    def share_wire(self, mask: int, invert: int = 0) -> None:
        """Put the CTPs in ``mask`` on one shared wire resting at the pull for ``invert``."""
        self.dut.ctp_wire_group_pull.value = WIRE_OR_POLARITY[invert].pull
        self.set_input("ctp_wire_group", mask)
        self.log.info("shared wire: CTP mask 0x%04x, pull %d", mask, WIRE_OR_POLARITY[invert].pull)

    async def assert_wire(self, index: int, cycles: int = SOURCE_HOLD_CYCLES) -> int:
        """The chiplet on CTP ``index``'s wire pulls it for ``cycles`` clocks; return the start cycle."""
        return await self.pulse_input_bit("ctp_wire_ext_assert", index, cycles)

    async def wait_bit(self, signal, bit: int, level: int, timeout_cycles: int, what: str) -> int:
        """Wait (falling-edge sampling) for one bit of a packed output."""
        for cycle in range(timeout_cycles):
            await FallingEdge(self.dut.clk)
            if (int(signal.value) >> bit) & 1 == level:
                return cycle
        raise AssertionError(
            f"{what}: expected bit {bit} at level {level} within {timeout_cycles} "
            f"cycles, observed vector 0x{int(signal.value):x}"
        )

    async def measure_bit_high(self, signal, bit: int, timeout_cycles: int, what: str) -> int:
        """Count falling-edge samples one packed-output bit stays high."""
        cycles = 0
        while (int(signal.value) >> bit) & 1:
            cycles += 1
            assert cycles <= timeout_cycles, (
                f"{what}: bit {bit} still high after {timeout_cycles} cycles"
            )
            await FallingEdge(self.dut.clk)
        return cycles

    async def check_bit_quiet(self, signal, bit: int, cycles: int, what: str) -> None:
        """Require one packed-output bit to stay low for ``cycles`` samples."""
        for cycle in range(cycles):
            await FallingEdge(self.dut.clk)
            observed = (int(signal.value) >> bit) & 1
            assert observed == 0, f"{what}: bit {bit} unexpectedly asserted at sample {cycle}"

    async def quiesce(self, cycles: int = E2E_LATENCY) -> None:
        """Clear every driven input and let the network drain."""
        for name in DRIVEN_INPUTS:
            self.set_input(name, 0)
        self.dut.jtag_clock_stop.value = 0
        await ClockCycles(self.dut.clk, cycles)


class BitWatcher:
    """Count distinct high phases of one packed-output bit in the background.

    Used both to prove a routed observable fired exactly once and to prove an
    unrouted observable stayed quiet while a positive control fired.
    """

    def __init__(self, tb: CtnTb, signal, bit: int, name: str) -> None:
        self._tb = tb
        self._signal = signal
        self._bit = bit
        self.name = name
        self.pulses = 0
        self.high_samples = 0
        self.rise_cycles: list[int] = []
        self._stop = False
        self._task = None

    def start(self) -> "BitWatcher":
        self.pulses = 0
        self.high_samples = 0
        self.rise_cycles = []
        self._stop = False
        self._task = cocotb.start_soon(self._run())
        return self

    async def _run(self) -> None:
        previous = 0
        while not self._stop:
            await FallingEdge(self._tb.dut.clk)
            level = (int(self._signal.value) >> self._bit) & 1
            if level:
                self.high_samples += 1
                if not previous:
                    self.pulses += 1
                    self.rise_cycles.append(current_cycle())
            previous = level

    async def stop(self) -> "BitWatcher":
        self._stop = True
        await self._task
        return self


__all__ = [
    "BOARD_INPUTS",
    "CLK_PERIOD_NS",
    "CT_DST_LATENCY",
    "CTM_BASE_ADDR",
    "CTM_REG_END",
    "CTM_SELECT_MASK",
    "CTP_BASE_ADDR",
    "CTP_CONFIG_OFFSET",
    "CTP_STATUS_BUSY_BIT",
    "CTP_STATUS_OFFSET",
    "CTP_STRETCH_OFFSET",
    "CTP_STRIDE",
    "DRIVEN_INPUTS",
    "E2E_LATENCY",
    "EXT_WIRE_OR_STRETCH",
    "INT_WIRE_OR_STRETCH",
    "NUM_CLK_STOP_REQ",
    "NUM_CTM_PORTS",
    "NUM_CTP",
    "NUM_INT_CT",
    "NUM_INT_CT_WIRE_OR",
    "SOURCE_HOLD_CYCLES",
    "UNMAPPED_ADDR",
    "WIRE_OR_POLARITY",
    "BitWatcher",
    "CtnTb",
    "WirePolarity",
    "ctm_src_cfg_addr",
    "ctp_addr",
    "current_cycle",
    "int_ct_matrix_port",
    "is_int_ct_wire_or",
    "random_seed",
]
