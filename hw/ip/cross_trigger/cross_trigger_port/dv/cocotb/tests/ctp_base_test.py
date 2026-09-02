# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the Cross Trigger Port IP-level cocotb tests.

The bench drives three surfaces of ``cross_trigger_port_tb_top``:

* the AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only);
* the core-side ``ct_src`` pulse input;
* the GPIO pad pins (``ct_req_out_din``, ``ct_req_in_din``, ``ct_ack_in_din``
  as inputs; the ``*_en``/``*_dout`` pad controls and ``ct_dst``/``busy`` as
  observables).

Register expectations come from ``cross_trigger_port.rdl`` (via the generated
Python header); protocol expectations come from
``hw/ip/cross_trigger/cross_trigger_port/doc/{architecture,interface}.adoc``.

Signal-sense convention used throughout: a GPIO input's LOGICAL level is
``raw ^ INVERT`` (the spec applies the optional inversion after the 2-FF
synchronizer). CONFIG.INVERT=0 pairs with active-low wire-OR signaling and
active-high point-to-point signaling; INVERT=1 swaps both senses and also
inverts the pad data outputs.
"""

from __future__ import annotations

import logging
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cross_trigger_port_reg import (
    CONFIG_REG_ADDR,
    CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT,
    CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT,
    CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT,
    STATUS_REG_ADDR,
    STRETCH_MULT_REG_ADDR,
)
from ocah_axi_vip import OcahAxiLiteMasterAgent

CLK_PERIOD_NS = 10

# CONFIG fields (cross_trigger_port.rdl).
CONFIG_MODE_BIT = 0  # 0 = Wire-OR, 1 = Point-to-Point
CONFIG_INVERT_BIT = 1  # invert the sense of all GPIO inputs and outputs
CONFIG_RESET_BIT = 2  # force-clear the P2P request output (deadlock recovery)
CONFIG_WMASK = 0x7

# STATUS fields (cross_trigger_port.rdl); all read-only hardware readouts.
STATUS_BUSY_BIT = 0
STATUS_REQ_OUT_BIT = 4
STATUS_ACK_IN_BIT = 5
STATUS_REQ_IN_BIT = 6
STATUS_ACK_OUT_BIT = 7

STRETCH_MULT_WMASK = 0xFFFF

# Bounded worst-case GPIO-input-to-observable latency in clk cycles: 2-FF
# synchronizer + inversion mux + edge detect / FSM step + registered output.
GPIO_SYNC_LATENCY = 8

# Mode -> expected pad enable levels, from the interface spec's signal table
# (interface.adoc): wire-OR listens on the shared CT_Req_out wire only; P2P
# drives CT_Req_out/CT_Ack_out and listens on CT_Req_in/CT_Ack_in.
PAD_ENABLE_EXPECT = {
    "wire_or": {
        "ct_req_out_din_en": 1,
        "ct_req_in_din_en": 0,
        "ct_ack_in_din_en": 0,
        "ct_ack_out_dout_en": 0,
    },
    "p2p": {
        "ct_req_out_dout_en": 1,
        "ct_req_out_din_en": 0,
        "ct_req_in_din_en": 1,
        "ct_ack_in_din_en": 1,
        "ct_ack_out_dout_en": 1,
    },
}


def random_seed() -> int:
    """Runner-provided seed (run_dv.py --seed -> RANDOM_SEED); default 1."""
    return int(os.environ.get("RANDOM_SEED", "1"), 0)


def config_value(mode: int = 0, invert: int = 0, reset: int = 0) -> int:
    """Pack the CONFIG register fields."""
    return (
        ((mode & 1) << CONFIG_MODE_BIT)
        | ((invert & 1) << CONFIG_INVERT_BIT)
        | ((reset & 1) << CONFIG_RESET_BIT)
    )


def decode_status(value: int) -> dict[str, int]:
    """Unpack a STATUS read into named fields (all logical-sense readouts)."""
    return {
        "busy": (value >> STATUS_BUSY_BIT) & 1,
        "req_out": (value >> STATUS_REQ_OUT_BIT) & 1,
        "ack_in": (value >> STATUS_ACK_IN_BIT) & 1,
        "req_in": (value >> STATUS_REQ_IN_BIT) & 1,
        "ack_out": (value >> STATUS_ACK_OUT_BIT) & 1,
    }


class CtpTb:
    """Clock/reset bring-up, register access, and pin-level helpers."""

    def __init__(self, dut, name: str = "ctp_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self._ct_dst_count = 0
        self._ct_dst_watcher = None

    # ------------------------------------------------------------------
    # Bring-up
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Init inputs, start the clock, run reset, and bring up the VIP."""
        dut = self.dut
        dut.ct_src.value = 0
        dut.ct_req_out_din.value = 0
        dut.ct_req_in_din.value = 0
        dut.ct_ack_in_din.value = 0
        dut.rst_n.value = 0

        cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())

        # The VIP master idles the AXI request pins from construction on.
        self.agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "axil",
            dut.clk,
            dut.rst_n,
            name="ctp_axil_host",
            timeout_cycles=1000,
        )
        self.seq = self.agent.sequence
        await self.agent.start()

        await ClockCycles(dut.clk, 5)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 5)
        self.log.info("bring-up complete: reset released, AXI-Lite master idle")

    # ------------------------------------------------------------------
    # Register access
    # ------------------------------------------------------------------

    async def write_config(self, mode: int = 0, invert: int = 0, reset: int = 0) -> None:
        value = config_value(mode, invert, reset)
        self.log.info("CONFIG <= 0x%x (MODE=%d INVERT=%d RESET=%d)", value, mode, invert, reset)
        await self.seq.write(CONFIG_REG_ADDR, value)

    async def read_config(self) -> int:
        return await self.seq.read(CONFIG_REG_ADDR)

    async def write_stretch_mult(self, value: int) -> None:
        self.log.info("STRETCH_MULT <= %d (pulse width %d cycles)", value, value + 1)
        await self.seq.write(STRETCH_MULT_REG_ADDR, value)

    async def read_status(self) -> dict[str, int]:
        raw = await self.seq.read(STATUS_REG_ADDR)
        fields = decode_status(raw)
        self.log.info(
            "STATUS = 0x%02x (busy=%d req_out=%d ack_in=%d req_in=%d ack_out=%d)",
            raw,
            fields["busy"],
            fields["req_out"],
            fields["ack_in"],
            fields["req_in"],
            fields["ack_out"],
        )
        return fields

    # ------------------------------------------------------------------
    # Pin-level stimulus and observation
    # ------------------------------------------------------------------

    async def pulse_ct_src(self) -> None:
        """Drive a single-cycle core-side source pulse."""
        dut = self.dut
        await RisingEdge(dut.clk)
        dut.ct_src.value = 1
        await RisingEdge(dut.clk)
        dut.ct_src.value = 0

    async def wait_level(self, signal, level: int, timeout_cycles: int, what: str) -> int:
        """Wait (sampling on falling edges) until ``signal == level``.

        Returns the number of cycles waited; raises on timeout so the caller's
        log carries the feature context.
        """
        for cycle in range(timeout_cycles):
            await FallingEdge(self.dut.clk)
            if int(signal.value) == level:
                return cycle
        raise AssertionError(
            f"{what}: expected level {level} within {timeout_cycles} cycles, "
            f"still {int(signal.value)}"
        )

    async def measure_high_cycles(self, signal, timeout_cycles: int, what: str) -> int:
        """Measure how many falling-edge samples ``signal`` stays high.

        Assumes the signal is currently high (use :meth:`wait_level` first).
        """
        cycles = 0
        while int(signal.value) == 1:
            cycles += 1
            if cycles > timeout_cycles:
                raise AssertionError(f"{what}: still high after {timeout_cycles} cycles")
            await FallingEdge(self.dut.clk)
        return cycles

    def start_ct_dst_watcher(self) -> None:
        """Count 1-cycle ct_dst pulses in the background (width-checked)."""
        self._ct_dst_count = 0
        if self._ct_dst_watcher is None:
            self._ct_dst_watcher = cocotb.start_soon(self._watch_ct_dst())

    def ct_dst_pulses(self) -> int:
        return self._ct_dst_count

    def clear_ct_dst_pulses(self) -> None:
        self._ct_dst_count = 0

    async def _watch_ct_dst(self) -> None:
        dut = self.dut
        while True:
            await FallingEdge(dut.clk)
            if int(dut.ct_dst.value) == 1:
                self._ct_dst_count += 1
                await FallingEdge(dut.clk)
                # ct_dst is a single-cycle pulse per the architecture spec's
                # receiver FSM description; two consecutive high samples mean
                # the pulse contract is broken.
                assert int(dut.ct_dst.value) == 0, (
                    f"ct_dst pulse wider than 1 cycle (pulse #{self._ct_dst_count})"
                )

    def check_pad_enables(self, mode_name: str) -> None:
        """Compare the pad enable pins against the interface-spec table."""
        dut = self.dut
        for pin, expected in PAD_ENABLE_EXPECT[mode_name].items():
            observed = int(getattr(dut, pin).value)
            assert observed == expected, (
                f"pad enable matrix ({mode_name}): {pin} expected {expected}, observed {observed}"
            )
        self.log.info("pad enable matrix (%s): all levels match the spec table", mode_name)

    async def settle(self, cycles: int = GPIO_SYNC_LATENCY * 2) -> None:
        """Let synchronizers/FSMs flush after a config or idle-level change."""
        await ClockCycles(self.dut.clk, cycles)
        self.clear_ct_dst_pulses()


__all__ = [
    "CLK_PERIOD_NS",
    "CONFIG_REG_ADDR",
    "CONFIG_WMASK",
    "CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT",
    "CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT",
    "CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT",
    "GPIO_SYNC_LATENCY",
    "STATUS_REG_ADDR",
    "STRETCH_MULT_REG_ADDR",
    "STRETCH_MULT_WMASK",
    "CtpTb",
    "config_value",
    "decode_status",
    "random_seed",
]
