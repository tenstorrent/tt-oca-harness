# SPDX-License-Identifier: Apache-2.0
"""DTP XTRIG cocotb helpers for flattened AXI-Lite and GPIO pins."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
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


class DtpFlatAxiLiteMaster:
    """Minimal AXI-Lite master for the flattened `xtrig_axil_*` top ports."""

    def __init__(self, dut, prefix: str, clk) -> None:
        self.dut = dut
        self.prefix = prefix
        self.clk = clk

    def _sig(self, suffix: str):
        return getattr(self.dut, f"{self.prefix}_{suffix}")

    def init_signals(self) -> None:
        for name in (
            "awaddr",
            "awprot",
            "awvalid",
            "wdata",
            "wstrb",
            "wvalid",
            "bready",
            "araddr",
            "arprot",
            "arvalid",
            "rready",
        ):
            self._sig(name).value = 0

    async def write(self, addr: int, data: int, *, wstrb: int = 0xF, prot: int = 0) -> int:
        """Issue one AXI-Lite write and return BRESP."""
        self._sig("awaddr").value = addr & 0xFFFFFFFF
        self._sig("awprot").value = prot & 0x7
        self._sig("awvalid").value = 1
        self._sig("wdata").value = data & 0xFFFFFFFF
        self._sig("wstrb").value = wstrb & 0xF
        self._sig("wvalid").value = 1
        self._sig("bready").value = 1

        aw_done = False
        w_done = False
        while not (aw_done and w_done):
            await RisingEdge(self.clk)
            if not aw_done and _int(self._sig("awready")):
                self._sig("awvalid").value = 0
                aw_done = True
            if not w_done and _int(self._sig("wready")):
                self._sig("wvalid").value = 0
                w_done = True

        while True:
            await RisingEdge(self.clk)
            if _int(self._sig("bvalid")):
                resp = _int(self._sig("bresp"))
                self._sig("bready").value = 0
                return resp

    async def read(self, addr: int, *, prot: int = 0) -> tuple[int, int]:
        """Issue one AXI-Lite read and return (RDATA, RRESP)."""
        self._sig("araddr").value = addr & 0xFFFFFFFF
        self._sig("arprot").value = prot & 0x7
        self._sig("arvalid").value = 1
        self._sig("rready").value = 1

        while True:
            await RisingEdge(self.clk)
            if _int(self._sig("arready")):
                self._sig("arvalid").value = 0
                break

        while True:
            await RisingEdge(self.clk)
            if _int(self._sig("rvalid")):
                data = _int(self._sig("rdata"))
                resp = _int(self._sig("rresp"))
                self._sig("rready").value = 0
                return data, resp

    async def write_skewed(
        self,
        addr: int,
        data: int,
        *,
        wstrb: int = 0xF,
        aw_before_w: bool = True,
        gap_cycles: int = 3,
        bready_delay: int = 0,
        timeout_cycles: int = 80,
    ) -> int:
        """Issue one write with explicit AW/W arrival skew.

        AXI-Lite permits AW and W to arrive independently. These manual accesses
        keep the non-arriving channel valid-low for a few cycles so demux and
        regblock channel-ordering paths are observable from the test log.
        """
        self._sig("bready").value = 0
        first = "aw" if aw_before_w else "w"
        second = "w" if aw_before_w else "aw"
        aw_done = False
        w_done = False
        self._drive_write_channel(first, addr, data, wstrb)
        for _ in range(gap_cycles):
            await RisingEdge(self.clk)
            if not aw_done and _int(self._sig("awvalid")) and _int(self._sig("awready")):
                self._sig("awvalid").value = 0
                aw_done = True
            if not w_done and _int(self._sig("wvalid")) and _int(self._sig("wready")):
                self._sig("wvalid").value = 0
                w_done = True
        self._drive_write_channel(second, addr, data, wstrb)

        for _ in range(timeout_cycles):
            await RisingEdge(self.clk)
            if not aw_done and _int(self._sig("awvalid")) and _int(self._sig("awready")):
                self._sig("awvalid").value = 0
                aw_done = True
            if not w_done and _int(self._sig("wvalid")) and _int(self._sig("wready")):
                self._sig("wvalid").value = 0
                w_done = True
            if aw_done and w_done:
                break
        else:
            self._sig("awvalid").value = 0
            self._sig("wvalid").value = 0
            raise TimeoutError(
                f"AXI-Lite skewed write timed out: addr=0x{addr:x} aw_done={aw_done} w_done={w_done}"
            )

        await ClockCycles(self.clk, bready_delay)
        self._sig("bready").value = 1
        for _ in range(timeout_cycles):
            await RisingEdge(self.clk)
            if _int(self._sig("bvalid")):
                resp = _int(self._sig("bresp"))
                self._sig("bready").value = 0
                return resp
        self._sig("bready").value = 0
        raise TimeoutError(f"AXI-Lite skewed write response timed out: addr=0x{addr:x}")

    def _drive_write_channel(self, channel: str, addr: int, data: int, wstrb: int) -> None:
        if channel == "aw":
            self._sig("awaddr").value = addr & 0xFFFFFFFF
            self._sig("awprot").value = 0
            self._sig("awvalid").value = 1
        elif channel == "w":
            self._sig("wdata").value = data & 0xFFFFFFFF
            self._sig("wstrb").value = wstrb & 0xF
            self._sig("wvalid").value = 1
        else:
            raise ValueError(f"unknown AXI-Lite write channel {channel}")

    async def _wait_write_channel_accept(self, channel: str) -> None:
        valid = "awvalid" if channel == "aw" else "wvalid"
        ready = "awready" if channel == "aw" else "wready"
        while True:
            await RisingEdge(self.clk)
            if _int(self._sig(ready)):
                self._sig(valid).value = 0
                return

    async def read_with_rready_hold(
        self,
        addr: int,
        *,
        hold_cycles: int = 4,
        prot: int = 0,
    ) -> tuple[int, int, int]:
        """Issue one read, hold RREADY low, then return (RDATA, RRESP, stable_data)."""
        self._sig("araddr").value = addr & 0xFFFFFFFF
        self._sig("arprot").value = prot & 0x7
        self._sig("arvalid").value = 1
        self._sig("rready").value = 0
        while True:
            await RisingEdge(self.clk)
            if _int(self._sig("arready")):
                self._sig("arvalid").value = 0
                break

        while True:
            await RisingEdge(self.clk)
            if _int(self._sig("rvalid")):
                first_data = _int(self._sig("rdata"))
                first_resp = _int(self._sig("rresp"))
                break

        stable = 1
        for _ in range(hold_cycles):
            await RisingEdge(self.clk)
            stable &= int(_int(self._sig("rdata")) == first_data)
            stable &= int(_int(self._sig("rresp")) == first_resp)

        self._sig("rready").value = 1
        await RisingEdge(self.clk)
        self._sig("rready").value = 0
        return first_data, first_resp, stable


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
    """Publishes XTRIG AXI-Lite and GPIO BFMs through the shared cfg."""

    def build_phase(self) -> None:
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.axil = None
        self.bfm = None

    async def run_phase(self) -> None:
        dut = cocotb.top
        self.axil = DtpFlatAxiLiteMaster(dut, "xtrig_axil", dut.clk_i)
        self.bfm = DtpXtrigBfm(dut, dut.clk_i)
        self.axil.init_signals()
        self.bfm.init_signals()
        self.cfg.xtrig_axil = self.axil
        self.cfg.xtrig_bfm = self.bfm
        self.cfg.xtrig_num_ctp = XTRIG_NUM_CTP
        self.cfg.xtrig_num_int_ct = XTRIG_NUM_INT_CT
        await self.cfg.reset_done.wait()
        self.logger.info("DTP XTRIG AXI-Lite and GPIO BFMs ready")
