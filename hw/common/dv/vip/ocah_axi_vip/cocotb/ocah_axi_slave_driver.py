# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 slave driver: fault-capable memory-backed responder engine.

`OcahAxiSlaveDriver` is the cocotbext-backed RAM responder that answers AXI4
traffic on the wires, extended with the OCAH fault controls (one-shot
non-OKAY response injection and bounded READY backpressure) shared through
`OcahFaultMixin`. The test-facing backdoor/fault API lives in
`OcahAxiSlaveSequence`; the AXI4-Lite variant lives in
`ocah_axi_lite_slave_driver.py` and reuses the mixin from here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from cocotbext.axi import AxiBus
from cocotbext.axi.axi_ram import AxiRamRead, AxiRamWrite
from cocotbext.axi.constants import AxiBurstType, AxiProt, AxiResp
from cocotbext.axi.memory import Memory

__all__ = ["OcahAxiSlaveDriver", "OcahFaultMixin"]


def _pause_pattern(stall_cycles: int):
    """Continuously insert bounded READY stalls without risking a permanent hang."""
    while True:
        for _ in range(max(stall_cycles, 0)):
            yield True
        yield False


class OcahFaultMixin:
    """Shared one-shot response injection and READY backpressure API."""

    def _init_fault_state(self, name: str) -> None:
        self.write_errors: dict[int, AxiResp] = {}
        self.read_errors: dict[int, AxiResp] = {}
        self.log = logging.getLogger(name)

    def inject_error(
        self,
        addr: int,
        resp: int | AxiResp,
        *,
        read: bool = True,
        write: bool = True,
    ) -> None:
        """Program a one-shot non-OKAY response at a beat-aligned address."""
        response = AxiResp(int(resp))
        if write:
            self.write_errors[int(addr)] = response
        if read:
            self.read_errors[int(addr)] = response
        self.log.info(
            "Injecting AXI error addr=0x%08x resp=%s read=%d write=%d",
            addr,
            response.name,
            read,
            write,
        )

    def clear_errors(self) -> None:
        self.write_errors.clear()
        self.read_errors.clear()

    def enable_backpressure(self, *, channels: Iterable[str], stall_cycles: int) -> None:
        """Drive READY low in bounded repeating windows on selected channels."""
        selected = set(channels)
        if "aw" in selected:
            self.write_if.aw_channel.set_pause_generator(_pause_pattern(stall_cycles))
        if "w" in selected:
            self.write_if.w_channel.set_pause_generator(_pause_pattern(stall_cycles))
        if "ar" in selected:
            self.read_if.ar_channel.set_pause_generator(_pause_pattern(stall_cycles))
        self.log.info("Enabled AXI backpressure channels=%s stall=%d", selected, stall_cycles)

    def disable_backpressure(self) -> None:
        for channel in (
            self.write_if.aw_channel,
            self.write_if.w_channel,
            self.read_if.ar_channel,
        ):
            channel.clear_pause_generator()
            channel.pause = False
        self.log.info("Disabled AXI backpressure")


class _FaultAxiRamWrite(AxiRamWrite):
    def __init__(self, bus, clock, reset=None, reset_active_level=True, *, fault_owner, **kwargs):
        self.fault_owner = fault_owner
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)

    async def _process_write(self):
        while True:
            aw = await self.aw_channel.recv()
            awid = int(getattr(aw, "awid", 0))
            addr = int(aw.awaddr)
            length = int(getattr(aw, "awlen", 0))
            size = int(getattr(aw, "awsize", self.max_burst_size))
            burst = AxiBurstType(int(getattr(aw, "awburst", AxiBurstType.INCR)))
            prot = AxiProt(int(getattr(aw, "awprot", AxiProt.NONSECURE)))

            num_bytes = 2**size
            assert 0 < num_bytes <= self.byte_lanes
            aligned_addr = (addr // num_bytes) * num_bytes
            beats = length + 1
            transfer_size = num_bytes * beats

            if burst == AxiBurstType.WRAP:
                lower_wrap_boundary = (addr // transfer_size) * transfer_size
                upper_wrap_boundary = lower_wrap_boundary + transfer_size
            if burst == AxiBurstType.INCR:
                assert 0x1000 - (aligned_addr & 0xFFF) >= transfer_size

            cur_addr = aligned_addr
            b = self.b_channel._transaction_obj()
            b.bid = awid
            b.bresp = AxiResp.OKAY

            for beat in range(beats):
                cur_word_addr = (cur_addr // self.byte_lanes) * self.byte_lanes
                w = await self.w_channel.recv()
                strb = int(getattr(w, "wstrb", self.strb_mask)) if self.wstrb_present else self.strb_mask
                data = int(w.wdata).to_bytes(self.byte_lanes, "little")
                last = int(w.wlast)
                beat_resp = self.fault_owner.write_errors.pop(cur_word_addr, AxiResp.OKAY)
                if beat_resp != AxiResp.OKAY:
                    b.bresp = beat_resp

                if beat_resp == AxiResp.OKAY:
                    start_offset = None
                    for offset in range(self.byte_lanes + 1):
                        enabled = offset < self.byte_lanes and ((strb >> offset) & 0x1)
                        if enabled and start_offset is None:
                            start_offset = offset
                        if not enabled and start_offset is not None:
                            if offset != start_offset:
                                await self._write(cur_word_addr + start_offset, data[start_offset:offset])
                            start_offset = None

                assert last == (beat == beats - 1)
                self.log.info(
                    "Write beat awaddr=0x%08x awprot=%s strb=0x%x resp=%s",
                    cur_word_addr,
                    prot,
                    strb,
                    AxiResp(beat_resp).name,
                )
                if burst != AxiBurstType.FIXED:
                    cur_addr += num_bytes
                    if burst == AxiBurstType.WRAP and cur_addr == upper_wrap_boundary:
                        cur_addr = lower_wrap_boundary

            await self.b_channel.send(b)


class _FaultAxiRamRead(AxiRamRead):
    def __init__(self, bus, clock, reset=None, reset_active_level=True, *, fault_owner, **kwargs):
        self.fault_owner = fault_owner
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)

    async def _process_read(self):
        while True:
            ar = await self.ar_channel.recv()
            arid = int(getattr(ar, "arid", 0))
            addr = int(ar.araddr)
            length = int(getattr(ar, "arlen", 0))
            size = int(getattr(ar, "arsize", self.max_burst_size))
            burst = AxiBurstType(int(getattr(ar, "arburst", AxiBurstType.INCR)))
            prot = AxiProt(int(getattr(ar, "arprot", AxiProt.NONSECURE)))

            num_bytes = 2**size
            assert 0 < num_bytes <= self.byte_lanes
            aligned_addr = (addr // num_bytes) * num_bytes
            beats = length + 1
            transfer_size = num_bytes * beats

            if burst == AxiBurstType.WRAP:
                lower_wrap_boundary = (addr // transfer_size) * transfer_size
                upper_wrap_boundary = lower_wrap_boundary + transfer_size
            if burst == AxiBurstType.INCR:
                assert 0x1000 - (aligned_addr & 0xFFF) >= transfer_size

            cur_addr = aligned_addr
            for beat in range(beats):
                cur_word_addr = (cur_addr // self.byte_lanes) * self.byte_lanes
                r = self.r_channel._transaction_obj()
                r.rid = arid
                r.rlast = beat == beats - 1
                r.rresp = self.fault_owner.read_errors.pop(cur_word_addr, AxiResp.OKAY)
                data = bytes(self.byte_lanes) if r.rresp != AxiResp.OKAY else await self._read(cur_word_addr, self.byte_lanes)
                r.rdata = int.from_bytes(data, "little")
                await self.r_channel.send(r)
                self.log.info(
                    "Read beat araddr=0x%08x arprot=%s resp=%s",
                    cur_word_addr,
                    prot,
                    AxiResp(r.rresp).name,
                )
                if burst != AxiBurstType.FIXED:
                    cur_addr += num_bytes
                    if burst == AxiBurstType.WRAP and cur_addr == upper_wrap_boundary:
                        cur_addr = lower_wrap_boundary


class OcahAxiSlaveDriver(Memory, OcahFaultMixin):
    """cocotbext AXI4 RAM responder engine with OCAH fault-control APIs."""

    def __init__(self, bus, clock, reset=None, reset_active_level=True, size=2**64, mem=None, *, name="OcahAxiSlaveDriver", **kwargs):
        self.write_if = None
        self.read_if = None
        self._init_fault_state(name)
        Memory.__init__(self, size, mem, **kwargs)
        self.write_if = _FaultAxiRamWrite(
            bus.write,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=self.mem,
            fault_owner=self,
        )
        self.read_if = _FaultAxiRamRead(
            bus.read,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=self.mem,
            fault_owner=self,
        )

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, reset=None, **kwargs):
        return cls(AxiBus.from_prefix(dut, prefix), clock, reset, **kwargs)
