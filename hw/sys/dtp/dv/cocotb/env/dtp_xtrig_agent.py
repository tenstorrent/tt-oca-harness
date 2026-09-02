# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP XTRIG cocotb helpers: shared AXI-Lite master attach and GPIO pins.

The `xtrig_axil_*` CSR port is driven through the shared ``ocah_axi_vip``
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


class DtpXtrigBfm:
    """Drive and sample DTP XTRIG CTM/CTP pins."""

    def __init__(self, dut, clk) -> None:
        self.dut = dut
        self.clk = clk

    def init_signals(self) -> None:
        for name in (
            "xtrig_ctm_src_ack",
            "xtrig_ctm_dst_req",
            "xtrig_ctp_req_out_din",
            "xtrig_ctp_req_in_din",
            "xtrig_ctp_ack_in_din",
            "xtrig_ctp_ack_out_din",
        ):
            if hasattr(self.dut, name):
                getattr(self.dut, name).value = 0

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
        )
        sample = {name: _int(getattr(self.dut, name)) for name in names if hasattr(self.dut, name)}
        await NextTimeStep()
        return sample

    async def drive_internal_dst_pulse(self, int_idx: int, cycles: int = 1) -> None:
        mask = 1 << int_idx
        self.dut.xtrig_ctm_dst_req.value = _int(self.dut.xtrig_ctm_dst_req) | mask
        await ClockCycles(self.clk, cycles)
        self.dut.xtrig_ctm_dst_req.value = _int(self.dut.xtrig_ctm_dst_req) & ~mask

    async def drive_ctp_req_out_din_pulse(self, ctp_idx: int, cycles: int = 2) -> None:
        mask = 1 << ctp_idx
        self.dut.xtrig_ctp_req_out_din.value = _int(self.dut.xtrig_ctp_req_out_din) | mask
        await ClockCycles(self.clk, cycles)
        self.dut.xtrig_ctp_req_out_din.value = _int(self.dut.xtrig_ctp_req_out_din) & ~mask

    async def drive_ctp_p2p_req_in(self, ctp_idx: int, value: int) -> None:
        mask = 1 << ctp_idx
        current = _int(self.dut.xtrig_ctp_req_in_din)
        self.dut.xtrig_ctp_req_in_din.value = (current | mask) if value else (current & ~mask)
        await ClockCycles(self.clk, 1)

    async def drive_ctp_p2p_ack_in(self, ctp_idx: int, value: int) -> None:
        mask = 1 << ctp_idx
        current = _int(self.dut.xtrig_ctp_ack_in_din)
        self.dut.xtrig_ctp_ack_in_din.value = (current | mask) if value else (current & ~mask)
        await ClockCycles(self.clk, 1)

    async def pulse_ctm_dst_req(self, mask: int, cycles: int = 1) -> None:
        self.dut.xtrig_ctm_dst_req.value = mask & ((1 << XTRIG_NUM_INT_CT) - 1)
        await ClockCycles(self.clk, cycles)
        self.dut.xtrig_ctm_dst_req.value = 0

    async def clear_inputs(self) -> None:
        self.init_signals()
        await ClockCycles(self.clk, 1)

    async def measure_mask_width(self, name: str, mask: int, *, timeout_cycles: int = 80) -> int:
        """Return the consecutive-cycle width of the first observed masked pulse."""
        width = 0
        started = False
        for _ in range(timeout_cycles):
            await ReadOnly()
            active = bool(_int(getattr(self.dut, name)) & mask)
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
                activity[name] |= _int(getattr(self.dut, name))
            await NextTimeStep()
            await ClockCycles(self.clk, 1)
        return activity

    async def pulse_reset(self, cycles: int = 3) -> None:
        """Pulse system reset while keeping cocotb-driven XTRIG inputs idle."""
        self.init_signals()
        self.dut.rst_n_i.value = 0
        await ClockCycles(self.clk, cycles)
        self.dut.rst_n_i.value = 1
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
        self.axil_agent = None
        self.axil = None
        self.bfm = None

    async def run_phase(self) -> None:
        dut = cocotb.top
        # Tests judge response codes themselves (the decode-backpressure
        # scenario expects DECERR), so the sequence must return non-OKAY
        # responses instead of raising.
        self.axil_agent = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "xtrig_axil",
            dut.clk_i,
            dut.rst_n_i,
            name="dtp_xtrig_axil",
            raise_on_error=False,
        )
        await self.axil_agent.start()
        self.axil = self.axil_agent.sequence
        self.bfm = DtpXtrigBfm(dut, dut.clk_i)
        self.bfm.init_signals()
        self.cfg.xtrig_axil = self.axil
        self.cfg.xtrig_bfm = self.bfm
        self.cfg.xtrig_num_ctp = XTRIG_NUM_CTP
        self.cfg.xtrig_num_int_ct = XTRIG_NUM_INT_CT
        await self.cfg.reset_done.wait()
        self.logger.info("DTP XTRIG shared AXI-Lite master and GPIO BFM ready")
