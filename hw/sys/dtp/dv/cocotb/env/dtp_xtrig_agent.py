# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP XTRIG cocotb helpers: shared AXI-Lite master attach and GPIO pins.

The XTRIG CSR AXI-Lite port (u_xtrig_master_if) is driven through the shared ``ocah_axi_vip``
AXI-Lite master; its sequence API carries the protocol-control operations the
XTRIG scenarios need (``write_skewed_result``, ``read_hold_result``,
contiguous partial strobes).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly
from ocah_axi_vip import OcahAxiLiteMasterAgent
from pyuvm import ConfigDB, uvm_agent

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


class DtpXtrigActivityWindow:
    """Per-cycle OR and AND of named observables from ``start`` until ``stop``.

    Sampling happens in the read-only phase of every clock cycle, so a
    one-cycle pulse anywhere in the window lands in ``activity`` (OR of all
    samples) and a one-cycle drop lands in ``hold`` (AND of all samples), which
    is how an active-low request is seen. ``stop`` cancels the sampler and
    returns activity, hold, and the last sample.
    """

    ALL_ONES = (1 << 32) - 1

    def __init__(self, bfm: DtpXtrigBfm, names: tuple[str, ...]) -> None:
        self._bfm = bfm
        self.names = names
        self.activity = {name: 0 for name in names}
        self.hold = {name: self.ALL_ONES for name in names}
        self.last = {name: 0 for name in names}
        # Cycle offset (from start) at which each bit of each signal first rose.
        self.first_seen: dict[str, dict[int, int]] = {name: {} for name in names}
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
            value = self._bfm.tb_if.sample(name)
            new_bits = value & ~self.activity[name]
            while new_bits:
                bit = (new_bits & -new_bits).bit_length() - 1
                self.first_seen[name][bit] = self.cycles
                new_bits &= new_bits - 1
            self.activity[name] |= value
            self.hold[name] &= value
            self.last[name] = value
        self.cycles += 1

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
        for name in (
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctp_req_out_din",
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
            "xtrig_demux_aw_lock",
            "xtrig_demux_w_pending",
            "xtrig_ctp_busy",
        )
        sample = {name: self.tb_if.sample(name) for name in names if self.tb_if.has(name)}
        await NextTimeStep()
        return sample

    async def pulse_input_mask(
        self, ctp_mask: int, int_mask: int, *, ctp_invert: int = 0, cycles: int = 2
    ) -> None:
        """Pulse CTP request-out pads and internal CT requests in the same cycles.

        A pad of ``ctp_invert`` pulses low from its high idle level; every
        other pad pulses high from low. Bits outside the masks keep their
        levels.
        """
        ctp_mask &= (1 << XTRIG_NUM_CTP) - 1
        int_mask &= (1 << XTRIG_NUM_INT_CT) - 1
        ctp_rest = _int(self.pins.xtrig_ctp_req_out_din) & ~ctp_mask
        self.pins.xtrig_ctp_req_out_din.value = ctp_rest | (ctp_mask & ~ctp_invert)
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) | int_mask
        await ClockCycles(self.clk, cycles)
        self.pins.xtrig_ctp_req_out_din.value = ctp_rest | (ctp_mask & ctp_invert)
        self.pins.xtrig_ctm_dst_req.value = _int(self.pins.xtrig_ctm_dst_req) & ~int_mask

    def set_ctp_req_out_din(self, mask: int) -> None:
        """Drive the CTP request-out pad inputs to ``mask``."""
        self.pins.xtrig_ctp_req_out_din.value = mask & ((1 << XTRIG_NUM_CTP) - 1)

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

    async def drive_ctp_req_out_din_pulse(self, ctp_idx: int, cycles: int = 2) -> None:
        mask = 1 << ctp_idx
        self.pins.xtrig_ctp_req_out_din.value = _int(self.pins.xtrig_ctp_req_out_din) | mask
        await ClockCycles(self.clk, cycles)
        self.pins.xtrig_ctp_req_out_din.value = _int(self.pins.xtrig_ctp_req_out_din) & ~mask

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

    def activity_window(self, names: tuple[str, ...]) -> DtpXtrigActivityWindow:
        """Window sampler over ``names``; the caller starts and stops it."""
        return DtpXtrigActivityWindow(self, names)

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

    async def measure_mask_width(self, name: str, mask: int, *, timeout_cycles: int = 80) -> int:
        """Return the consecutive-cycle width of the first observed masked pulse."""
        width = 0
        started = False
        for _ in range(timeout_cycles):
            await ReadOnly()
            active = bool(self.tb_if.sample(name) & mask)
            await NextTimeStep()
            if active:
                width += 1
                started = True
            elif started:
                return width
            await ClockCycles(self.clk, 1)
        return width

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

    async def pulse_reset(self, cycles: int = 3) -> None:
        """Pulse system reset while keeping cocotb-driven XTRIG inputs idle."""
        self.init_signals()
        self.tb_if.sys_rst_n.value = 0
        await ClockCycles(self.clk, cycles)
        self.tb_if.sys_rst_n.value = 1
        await ClockCycles(self.clk, cycles + 2)

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

    async def run_phase(self) -> None:
        tb = self.tb_if
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
