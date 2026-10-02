# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP XTRIG cocotb helpers: shared AXI-Lite master attach and GPIO pins.

The XTRIG CSR AXI-Lite port (u_xtrig_master_if) is driven through the shared ``ocah_axi_vip``
AXI-Lite master; its sequence API carries the protocol-control operations the
XTRIG scenarios need (``write_skewed_result``, ``read_hold_result``,
contiguous partial strobes). A passive shared AXI-Lite monitor on the same
port publishes every completed transaction on ``item_ap`` for the
cross-trigger reference models.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly
from ocah_axi_vip import OcahAxiLiteMasterAgent, OcahAxiLiteMonitor
from pyuvm import ConfigDB, uvm_agent, uvm_analysis_port

from .dtp_xtrig_types import (
    XTRIG_CTP_STATUS_ACK_IN,
    XTRIG_CTP_STATUS_ACK_OUT,
    XTRIG_CTP_STATUS_BUSY,
    XTRIG_CTP_STATUS_REQ_IN,
    XTRIG_CTP_STATUS_REQ_OUT,
    XTRIG_NUM_CTP,
    XTRIG_NUM_INT_CT,
)


def _int(signal) -> int:
    return int(signal.value)


@dataclass(frozen=True)
class DtpXtrigPulse:
    """The width of the first masked pulse a measurement saw and the rises it counted."""

    width: int
    pulses: int


class DtpXtrigActivityWindow:
    """Per-cycle OR and AND of named observables from ``start`` until ``stop``.

    Sampling happens in the read-only phase of every clock cycle, so a
    one-cycle pulse anywhere in the window lands in ``activity`` (OR of all
    samples) and a one-cycle drop lands in ``hold`` (AND of all samples), which
    is how an active-low request is seen. ``first_seen`` holds the window
    cycle at which each bit first rose and ``rises`` how many times it rose.
    Each ``derived`` observable is a function of one sample of ``names``,
    evaluated every cycle and kept with the same records, a value of 0 before
    the window starting it. ``stop`` cancels the sampler and returns activity,
    hold, and the last sample.
    """

    ALL_ONES = (1 << 32) - 1

    def __init__(
        self,
        bfm: DtpXtrigBfm,
        names: tuple[str, ...],
        derived: Mapping[str, Callable[[dict[str, int]], int]] | None = None,
    ) -> None:
        self._bfm = bfm
        self.names = names
        self._derived = dict(derived or {})
        tracked = (*names, *self._derived)
        self.activity = {name: 0 for name in tracked}
        self.hold = {name: self.ALL_ONES for name in tracked}
        self.last = {name: 0 for name in tracked}
        # Cycle offset (from start) at which each bit of each signal first rose.
        self.first_seen: dict[str, dict[int, int]] = {name: {} for name in tracked}
        # Number of rises of each bit of each signal.
        self.rises: dict[str, dict[int, int]] = {name: {} for name in tracked}
        self.cycles = 0
        self._task: cocotb.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        while True:
            await ReadOnly()
            self._record()
            await NextTimeStep()
            await ClockCycles(self._bfm.clk, 1)

    def _record(self) -> None:
        for name in self.names:
            self._track(name, self._bfm.tb_if.sample(name))
        for name, derive in self._derived.items():
            self._track(name, derive(self.last))
        self.cycles += 1

    def _track(self, name: str, value: int) -> None:
        new_bits = value & ~self.activity[name]
        while new_bits:
            bit = (new_bits & -new_bits).bit_length() - 1
            self.first_seen[name][bit] = self.cycles
            new_bits &= new_bits - 1
        rose = value & ~self.last[name]
        while rose:
            bit = (rose & -rose).bit_length() - 1
            self.rises[name][bit] = self.rises[name].get(bit, 0) + 1
            rose &= rose - 1
        self.activity[name] |= value
        self.hold[name] &= value
        self.last[name] = value

    def first_seen_text(self, names: tuple[str, ...] | None = None) -> str:
        """``signal:bit@cycle`` list of every bit that rose, for the log."""
        parts = []
        for name in names or self.names:
            for bit, cycle in sorted(self.first_seen[name].items()):
                parts.append(f"{name.removeprefix('xtrig_')}:{bit}@{cycle}")
        return " ".join(parts) or "-"

    async def stop(self) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await ReadOnly()
        self._record()
        await NextTimeStep()
        return dict(self.activity), dict(self.hold), dict(self.last)


class DtpXtrigBfm:
    """Drive and sample DTP XTRIG CTM/CTP pins through dtp_xtrig_if."""

    def __init__(self, tb_if) -> None:
        self.tb_if = tb_if
        self.pins = tb_if.xtrig
        self.clk = tb_if.clk

    def init_signals(self) -> None:
        """Quiesce every stimulus vector; the wire pulls and the group describe the board and stay."""
        for name in (
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctp_wire_ext_assert",
            "xtrig_ctp_req_in_din",
            "xtrig_ctp_ack_in_din",
            "xtrig_ctp_ack_out_din",
        ):
            getattr(self.pins, name).value = 0

    async def sample(self) -> dict[str, int]:
        await ReadOnly()
        names = (
            "xtrig_ctm_src_req",
            "xtrig_ctm_dst_ack",
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctp_req_out_dout",
            "xtrig_ctp_req_out_dout_en",
            "xtrig_ctp_req_out_din",
            "xtrig_ctp_req_out_din_en",
            "xtrig_ctp_wire_ext_assert",
            "xtrig_ctp_wire_pull",
            "xtrig_ctp_wire_group",
            "xtrig_ctp_wire_mismatch",
            "xtrig_ctp_ct_dst",
            "xtrig_int_ct_dst",
            "xtrig_ctp_req_in_dout",
            "xtrig_ctp_req_in_dout_en",
            "xtrig_ctp_req_in_din",
            "xtrig_ctp_req_in_din_en",
            "xtrig_ctp_ack_in_dout",
            "xtrig_ctp_ack_in_dout_en",
            "xtrig_ctp_ack_in_din",
            "xtrig_ctp_ack_in_din_en",
            "xtrig_ctp_ack_out_dout",
            "xtrig_ctp_ack_out_dout_en",
            "xtrig_ctp_ack_out_din",
            "xtrig_ctp_ack_out_din_en",
            "xtrig_axil_awvalid_count",
            "xtrig_axil_wvalid_count",
            "xtrig_axil_arvalid_count",
            "xtrig_axil_aw_stall_count",
            "xtrig_axil_ar_stall_count",
            "xtrig_axil_w_stall_count",
            "xtrig_axil_aw_open_stall_count",
            "xtrig_axil_aw_open_accept_count",
            "xtrig_axil_ar_open_stall_count",
            "xtrig_axil_ar_open_accept_count",
            "xtrig_demux_aw_lock",
            "xtrig_demux_w_pending",
            "xtrig_ctp_busy",
        )
        sample = {name: self.tb_if.sample(name) for name in names if self.tb_if.has(name)}
        await NextTimeStep()
        return sample

    async def pulse_input_mask(self, ctp_mask: int, int_mask: int, *, cycles: int = 2) -> None:
        """Pull the shared wires of ``ctp_mask`` and request the internal CTs of ``int_mask``.

        The chiplet on each selected wire pulls it to the asserted level of
        its sense for ``cycles`` clocks; the internal requests rise for the
        same cycles. Bits outside the masks keep their state.
        """
        ctp_mask &= (1 << XTRIG_NUM_CTP) - 1
        int_mask &= (1 << XTRIG_NUM_INT_CT) - 1
        self.pins.xtrig_ctp_wire_ext_assert.value = (
            _int(self.pins.xtrig_ctp_wire_ext_assert) | ctp_mask
        )
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) | int_mask
        await ClockCycles(self.clk, cycles)
        self.pins.xtrig_ctp_wire_ext_assert.value = (
            _int(self.pins.xtrig_ctp_wire_ext_assert) & ~ctp_mask
        )
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) & ~int_mask

    def set_ctp_wire_pull(self, mask: int) -> None:
        """Rest each CTP's private wire at the level of its bit in ``mask``."""
        self.pins.xtrig_ctp_wire_pull.value = mask & ((1 << XTRIG_NUM_CTP) - 1)

    def set_ctp_wire_ext_assert(self, mask: int) -> None:
        """The chiplets on the wires of ``mask`` pull them; the others release."""
        self.pins.xtrig_ctp_wire_ext_assert.value = mask & ((1 << XTRIG_NUM_CTP) - 1)

    def set_ctp_wire_group(self, mask: int, *, pull: int) -> None:
        """Put the CTPs of ``mask`` on one shared wire resting at ``pull``."""
        self.pins.xtrig_ctp_wire_group.value = mask & ((1 << XTRIG_NUM_CTP) - 1)
        self.pins.xtrig_ctp_wire_group_pull.value = pull & 1

    def set_ctp_req_in_din(self, mask: int) -> None:
        """Drive the CTP request-in pad inputs to ``mask``."""
        self.pins.xtrig_ctp_req_in_din.value = mask & ((1 << XTRIG_NUM_CTP) - 1)

    def set_sys_reset(self, *, active: bool) -> None:
        """Hold (``True``) or release the system reset."""
        self.tb_if.sys_rst_n.value = 0 if active else 1

    async def drive_internal_dst_pulse(self, int_idx: int, cycles: int = 1) -> None:
        mask = 1 << int_idx
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) | mask
        await ClockCycles(self.clk, cycles)
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) & ~mask

    async def pull_ctp_wire(self, ctp_idx: int, cycles: int = 2) -> None:
        """The chiplet on CTP ``ctp_idx``'s wire pulls it for ``cycles`` clocks."""
        await self.pulse_input_mask(1 << ctp_idx, 0, cycles=cycles)

    async def drive_ctp_p2p_req_in(self, ctp_idx: int, value: int) -> None:
        mask = 1 << ctp_idx
        current = _int(self.pins.xtrig_ctp_req_in_din)
        self.pins.xtrig_ctp_req_in_din.value = (current | mask) if value else (current & ~mask)
        await ClockCycles(self.clk, 1)

    async def drive_ctp_p2p_ack_in(self, ctp_idx: int, value: int) -> None:
        mask = 1 << ctp_idx
        current = _int(self.pins.xtrig_ctp_ack_in_din)
        self.pins.xtrig_ctp_ack_in_din.value = (current | mask) if value else (current & ~mask)
        await ClockCycles(self.clk, 1)

    async def pulse_ctm_dst_req(self, mask: int, cycles: int = 1) -> None:
        self.pins.xtrig_ctm_dst_req.value = mask & ((1 << XTRIG_NUM_INT_CT) - 1)
        await ClockCycles(self.clk, cycles)
        self.pins.xtrig_ctm_dst_req.value = 0

    def activity_window(
        self,
        names: tuple[str, ...],
        derived: Mapping[str, Callable[[dict[str, int]], int]] | None = None,
    ) -> DtpXtrigActivityWindow:
        """Window sampler over ``names`` and the ``derived`` observables; the caller starts and stops it."""
        return DtpXtrigActivityWindow(self, names, derived)

    def sample_signal(self, name: str) -> int:
        """Integer value of one cross-trigger observable or counter by its flat name."""
        return self.tb_if.sample(name)

    def set_ctp_ack_in_din(self, mask: int) -> None:
        """Drive the CTP ack-in pad inputs to ``mask``."""
        self.pins.xtrig_ctp_ack_in_din.value = mask & ((1 << XTRIG_NUM_CTP) - 1)

    def set_ctm_src_ack(self, mask: int) -> None:
        """Drive the CTM source-ack inputs to ``mask``."""
        self.pins.xtrig_ctm_src_ack.value = mask & ((1 << XTRIG_NUM_INT_CT) - 1)

    async def clear_inputs(self) -> None:
        self.init_signals()
        await ClockCycles(self.clk, 1)

    async def measure_mask_width(
        self, name: str, mask: int, *, timeout_cycles: int = 80, tail_cycles: int = 6
    ) -> DtpXtrigPulse:
        """Consecutive-cycle width of the first masked pulse, and the rises counted until ``tail_cycles`` after it ends.

        A masked value already nonzero at the first sample counts as a rise;
        the measurement ends at ``timeout_cycles`` samples in any case.
        """
        width = 0
        pulses = 0
        was_active = False
        ended_at: int | None = None
        for cycle in range(timeout_cycles):
            await ReadOnly()
            active = bool(self.tb_if.sample(name) & mask)
            await NextTimeStep()
            if active and not was_active:
                pulses += 1
            if ended_at is None:
                if active:
                    width += 1
                elif pulses:
                    ended_at = cycle
            was_active = active
            if ended_at is not None and cycle - ended_at >= tail_cycles:
                break
            await ClockCycles(self.clk, 1)
        return DtpXtrigPulse(width=width, pulses=pulses)

    async def assert_quiet(self, names: tuple[str, ...], *, cycles: int = 4) -> dict[str, int]:
        """Sample selected signal groups for a quiet window and return ORed activity."""
        activity = {name: 0 for name in names}
        for _ in range(cycles):
            await ReadOnly()
            for name in names:
                activity[name] |= self.tb_if.sample(name)
            await NextTimeStep()
            await ClockCycles(self.clk, 1)
        return activity

    @staticmethod
    def decode_status(status: int) -> dict[str, int]:
        return {
            "busy": 1 if status & XTRIG_CTP_STATUS_BUSY else 0,
            "req_out": 1 if status & XTRIG_CTP_STATUS_REQ_OUT else 0,
            "ack_in": 1 if status & XTRIG_CTP_STATUS_ACK_IN else 0,
            "req_in": 1 if status & XTRIG_CTP_STATUS_REQ_IN else 0,
            "ack_out": 1 if status & XTRIG_CTP_STATUS_ACK_OUT else 0,
        }


class DtpXtrigAgent(uvm_agent):
    """Publishes the shared XTRIG AXI-Lite master and the GPIO BFM through cfg."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.tb_if = ConfigDB().get(self, "", "tb_if")
        self.axil_agent = None
        self.axil = None
        self.bfm = None
        self.item_ap = uvm_analysis_port("item_ap", self)
        self.monitor: OcahAxiLiteMonitor | None = None

    async def run_phase(self) -> None:
        tb = self.tb_if
        self.monitor = OcahAxiLiteMonitor(
            tb.axi_bus("xtrig", passive=True),
            tb.clk,
            reset=tb.sys_rst_n,
            reset_active_level=False,
            name="dtp_xtrig_axil_monitor",
        )
        self.monitor.add_item_callback(self.item_ap.write)
        await self.monitor.start()
        # Tests judge response codes themselves (the decode-backpressure
        # scenario expects DECERR), so the sequence must return non-OKAY
        # responses instead of raising.
        self.axil_agent = OcahAxiLiteMasterAgent(
            tb.axi_bus("xtrig"),
            tb.clk,
            tb.sys_rst_n,
            name="dtp_xtrig_axil",
            raise_on_error=False,
        )
        await self.axil_agent.start()
        self.axil = self.axil_agent.sequence
        self.bfm = DtpXtrigBfm(tb)
        self.bfm.init_signals()
        self.cfg.xtrig_axil = self.axil
        self.cfg.xtrig_bfm = self.bfm
        self.cfg.xtrig_num_ctp = XTRIG_NUM_CTP
        self.cfg.xtrig_num_int_ct = XTRIG_NUM_INT_CT
        await self.cfg.reset_done.wait()
        self.logger.info("DTP XTRIG shared AXI-Lite master and GPIO BFM ready")
