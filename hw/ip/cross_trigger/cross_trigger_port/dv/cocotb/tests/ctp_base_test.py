# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the Cross Trigger Port IP-level cocotb tests.

The bench drives three surfaces of ``cross_trigger_port_tb_top``:

* the AXI4-Lite CSR port through the shared AXI VIP's AXI4-Lite master
  (``OcahAxiLiteMasterAgent`` on the flattened ``axil_*`` pins, consumed
  through ``agent.sequence`` only);
* the core-side ``ct_src`` pulse input;
* the GPIO pads. The CT_Req_out pad sits on the open-drain shared wire of
  ``tb_top``: ``wire_or_pull`` is the level the wire rests at, the two
  ``wire_or_ext_assert`` bits are external chiplets pulling the wire, and
  ``ct_req_out_din`` is the resolved wire the pad presents to the core.
  ``ct_req_in_din`` and ``ct_ack_in_din`` are the point-to-point pad inputs;
  the ``*_en``/``*_dout`` pad controls and ``ct_dst``/``busy`` are
  observables.

Register expectations come from ``cross_trigger_port.rdl`` (via the generated
Python header); protocol expectations come from
``hw/ip/cross_trigger/cross_trigger_port/doc/{architecture,interface}.adoc``.

Signal-sense convention: CONFIG.INVERT selects the pad polarity. In wire-OR
mode INVERT=0 is an active-low wire with a pull-up and INVERT=1 an
active-high wire with a pull-down (``WIRE_OR_POLARITY``). The core receives
a trigger when the synchronized wire moves from its rest level to its
asserted level, and its own pad pulls the wire to the asserted level for the
stretched window. In point-to-point mode INVERT=0 is active-high and
INVERT=1 active-low on every request and acknowledge pad. The optional
inversion sits after the two-stage synchronizer.

Verdicts are plain assertions whose messages carry the feature context and
the observed values, the convention of the pin-level cross-trigger IP
benches; the tests access the pins through :class:`CtpTb`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from itertools import zip_longest

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
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

# Clock edges from the edge at which the shared wire moves to the edge at
# which ct_dst is high: the two synchronizer stages and the registered ct_dst
# output (architecture spec, signal synchronization table; interface spec,
# ct_dst_o).
CT_DST_LATENCY = 3

# Cycles the receive model waits before comparing, so that every pulse it
# predicted has had time to appear.
RECEIVE_SETTLE_CYCLES = CT_DST_LATENCY + 2

# Number of external open-drain drivers tb_top places on the shared wire.
NUM_EXT_DRIVERS = 2


@dataclass(frozen=True)
class WirePolarity:
    """Rest and asserted levels of the shared wire for one INVERT sense."""

    pull: int
    assert_level: int


# CONFIG.INVERT -> shared-wire polarity in wire-OR mode (cross_trigger_port.rdl):
# INVERT=0 is active-low with a pull-up, INVERT=1 active-high with a pull-down.
WIRE_OR_POLARITY = {
    0: WirePolarity(pull=1, assert_level=0),
    1: WirePolarity(pull=0, assert_level=1),
}

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


def current_cycle() -> int:
    """Index of the current clock cycle, counted from the first rising edge.

    Derived from simulation time so every coroutine, whichever edge it woke
    on, agrees on the index of the cycle it is in.
    """
    return int(get_sim_time("ns") // CLK_PERIOD_NS)


class WireOrReceiveModel:
    """Cycle-exact model of the wire-OR receive path of ``cross_trigger_port``.

    Samples the resolved shared wire and the DUT's effective CONFIG fields
    once per cycle, replays the two-stage synchronizer (reset value 0),
    applies INVERT after it, and predicts one ``ct_dst`` pulse in the cycle
    after the sensed wire moves from rest (1) to asserted (0) while the port
    is in wire-OR mode. :meth:`check` compares the predicted cycles with the
    pulses the ``ct_dst`` watcher recorded and reports the first difference.
    The model also records every cycle in which ``tb_top`` flags an enabled
    driver that drives the wire's pull level.
    """

    def __init__(self, tb: CtpTb) -> None:
        self._tb = tb
        self.predicted: list[int] = []
        self.mismatch_cycles: list[int] = []
        self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None

    def start(self) -> None:
        if self._task is None:
            self._task = cocotb.start_soon(self._run())

    def clear(self) -> None:
        self.predicted.clear()
        self.mismatch_cycles.clear()
        self._tb.clear_ct_dst_pulses()

    async def _run(self) -> None:
        dut = self._tb.dut
        in_reset_prev = True
        raw_prev = 0
        sync1_prev = 0
        sensed_prev = 0
        while True:
            await FallingEdge(dut.clk)
            cycle = current_cycle()
            rst = int(dut.rst_n.value)
            raw = int(dut.ct_req_out_din.value)
            invert = int(dut.cfg_invert.value)
            mode_wire_or = int(dut.cfg_mode_wire_or.value)
            # State held during this cycle: the asynchronous reset holds
            # every stage at 0 through the edge that opened the cycle.
            if rst == 0 or in_reset_prev:
                sync1, sync2, prev_sensed = 0, 0, 0
            else:
                sync1, sync2, prev_sensed = raw_prev, sync1_prev, sensed_prev
            sensed = sync2 ^ invert
            if rst == 1 and mode_wire_or == 1 and prev_sensed == 1 and sensed == 0:
                self.predicted.append(cycle + 1)
            if int(dut.wire_or_drive_mismatch.value) == 1:
                self.mismatch_cycles.append(cycle)
            in_reset_prev = rst == 0
            raw_prev = raw
            sync1_prev = sync1
            sensed_prev = sensed

    def check(
        self, what: str, *, expected_count: int | None = None, allow_mismatch: bool = False
    ) -> int:
        """Compare predicted and observed ``ct_dst`` cycles, then clear both.

        ``expected_count`` is the scenario's own count of wire assertions; it
        keeps the model honest by failing a scenario whose stimulus never
        reached the wire. Returns the number of cycles the pull mismatch flag
        was set; with ``allow_mismatch`` false any such cycle fails.
        """
        predicted = list(self.predicted)
        observed = list(self._tb.ct_dst_cycles())
        mismatch = list(self.mismatch_cycles)
        self.clear()
        self._tb.log.info(
            "%s: wire assertions predicted ct_dst at %s, observed ct_dst at %s",
            what,
            predicted,
            observed,
        )
        if expected_count is not None:
            assert len(predicted) == expected_count, (
                f"{what}: the wire carried {len(predicted)} assertion edges "
                f"(ct_dst predicted at {predicted}), the scenario expected {expected_count}"
            )
        for index, (pred, obs) in enumerate(zip_longest(predicted, observed)):
            assert pred == obs, (
                f"{what}: ct_dst pulse #{index} predicted at cycle {pred} "
                f"({CT_DST_LATENCY} after the wire assertion edge) but observed at {obs}; "
                f"predicted {predicted}, observed {observed}"
            )
        if not allow_mismatch:
            assert not mismatch, (
                f"{what}: an enabled driver drove the wire's pull level in cycles {mismatch}"
            )
        return len(mismatch)

    async def expect(
        self, what: str, *, expected_count: int | None = None, allow_mismatch: bool = False
    ) -> int:
        """Wait for the last predicted pulse to appear, then :meth:`check`."""
        await ClockCycles(self._tb.dut.clk, RECEIVE_SETTLE_CYCLES)
        return self.check(what, expected_count=expected_count, allow_mismatch=allow_mismatch)


class CtpTb:
    """Clock/reset bring-up, register access, and pin-level helpers."""

    def __init__(self, dut, name: str = "ctp_tb") -> None:
        self.dut = dut
        self.log = logging.getLogger(f"cocotb.tb.{name}")
        self.agent = None
        self.seq = None
        self._ct_dst_count = 0
        self._ct_dst_cycles: list[int] = []
        self._ct_dst_watcher = None
        self.receive = WireOrReceiveModel(self)

    # ------------------------------------------------------------------
    # Bring-up
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Init inputs, start the clock, run reset, and bring up the VIP.

        The shared wire rests at the pull of the reset-default sense
        (INVERT=0) with no external driver pulling.
        """
        dut = self.dut
        dut.ct_src.value = 0
        dut.wire_or_ext_assert.value = 0
        dut.wire_or_pull.value = WIRE_OR_POLARITY[0].pull
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

    async def pulse_reset(self, cycles: int = 3) -> None:
        """Assert the asynchronous reset for ``cycles`` clocks with the CSR port idle."""
        dut = self.dut
        await RisingEdge(dut.clk)
        dut.rst_n.value = 0
        self.log.info("reset asserted at cycle %d for %d cycles", current_cycle(), cycles)
        await ClockCycles(dut.clk, cycles)
        dut.rst_n.value = 1

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
    # Shared-wire stimulus
    # ------------------------------------------------------------------

    def set_wire_pull(self, invert: int) -> None:
        """Rest the shared wire at the pull of the board built for ``invert``."""
        pull = WIRE_OR_POLARITY[invert].pull
        self.dut.wire_or_pull.value = pull
        self.log.info("shared wire pull <= %d (board for INVERT=%d)", pull, invert)

    def ext_mask(self) -> int:
        return int(self.dut.wire_or_ext_assert.value)

    def set_ext_now(self, mask: int) -> None:
        """Set the external drivers in the current cycle (bit set = pulling)."""
        self.dut.wire_or_ext_assert.value = mask & ((1 << NUM_EXT_DRIVERS) - 1)

    async def drive_ext(self, mask: int) -> int:
        """At the next rising edge set the external drivers to ``mask``; return that cycle."""
        await RisingEdge(self.dut.clk)
        self.set_ext_now(mask)
        return current_cycle()

    async def ext_pulse(self, driver: int, cycles: int) -> int:
        """External chiplet ``driver`` pulls the wire for ``cycles`` clocks.

        Returns the cycle in which the pull began. Other drivers keep their
        state.
        """
        bit = 1 << driver
        start = await self.drive_ext(self.ext_mask() | bit)
        if cycles > 1:
            await ClockCycles(self.dut.clk, cycles - 1)
        await self.drive_ext(self.ext_mask() & ~bit)
        return start

    # ------------------------------------------------------------------
    # Pin-level stimulus and observation
    # ------------------------------------------------------------------

    async def pulse_ct_src(self) -> int:
        """Drive a single-cycle core-side source pulse; return its cycle."""
        dut = self.dut
        await RisingEdge(dut.clk)
        dut.ct_src.value = 1
        cycle = current_cycle()
        await RisingEdge(dut.clk)
        dut.ct_src.value = 0
        return cycle

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
        self.clear_ct_dst_pulses()
        if self._ct_dst_watcher is None:
            self._ct_dst_watcher = cocotb.start_soon(self._watch_ct_dst())

    def ct_dst_pulses(self) -> int:
        return self._ct_dst_count

    def ct_dst_cycles(self) -> list[int]:
        """Cycles in which the watcher saw ``ct_dst`` high, oldest first."""
        return list(self._ct_dst_cycles)

    def clear_ct_dst_pulses(self) -> None:
        self._ct_dst_count = 0
        self._ct_dst_cycles.clear()

    async def _watch_ct_dst(self) -> None:
        dut = self.dut
        while True:
            await FallingEdge(dut.clk)
            if int(dut.ct_dst.value) == 1:
                self._ct_dst_count += 1
                self._ct_dst_cycles.append(current_cycle())
                await FallingEdge(dut.clk)
                # ct_dst is a single-cycle pulse per the architecture spec's
                # receiver FSM description; two consecutive high samples mean
                # the pulse contract is broken.
                assert int(dut.ct_dst.value) == 0, (
                    f"ct_dst pulse wider than 1 cycle (pulse #{self._ct_dst_count})"
                )

    async def expect_ct_dst_at(
        self, assert_cycle: int, before: int, what: str, *, count: int = 1
    ) -> None:
        """``count`` new ``ct_dst`` pulses, the first ``CT_DST_LATENCY`` after ``assert_cycle``.

        ``before`` is the pulse count taken before the stimulus.
        """
        await ClockCycles(self.dut.clk, RECEIVE_SETTLE_CYCLES)
        new = self.ct_dst_cycles()[before:]
        expected = assert_cycle + CT_DST_LATENCY
        assert len(new) == count and new[0] == expected, (
            f"{what}: wire asserted at cycle {assert_cycle}, expected {count} ct_dst pulse(s) "
            f"with the first at cycle {expected} ({CT_DST_LATENCY} cycles later), "
            f"observed pulses at {new}"
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
        """Let synchronizers/FSMs flush after a config or wire change.

        With the receive model running, the pulses of the transition are
        compared against it before the counts are cleared.
        """
        await ClockCycles(self.dut.clk, cycles)
        if self.receive.running:
            self.receive.check("settle")
        else:
            self.clear_ct_dst_pulses()


__all__ = [
    "CLK_PERIOD_NS",
    "CONFIG_REG_ADDR",
    "CONFIG_WMASK",
    "CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT",
    "CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT",
    "CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT",
    "CT_DST_LATENCY",
    "GPIO_SYNC_LATENCY",
    "NUM_EXT_DRIVERS",
    "RECEIVE_SETTLE_CYCLES",
    "STATUS_REG_ADDR",
    "STRETCH_MULT_REG_ADDR",
    "STRETCH_MULT_WMASK",
    "WIRE_OR_POLARITY",
    "CtpTb",
    "WireOrReceiveModel",
    "WirePolarity",
    "config_value",
    "current_cycle",
    "decode_status",
    "random_seed",
]
