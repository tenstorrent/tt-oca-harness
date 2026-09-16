# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite slave driver: fault-capable memory-backed responder engine.

`OcahAxiLiteSlaveDriver` is the cocotbext-backed AXI4-Lite RAM responder,
extended with the OCAH fault controls (one-shot non-OKAY response injection
and bounded READY backpressure) via `OcahFaultMixin` shared with the AXI4
slave driver. The test-facing backdoor/fault API lives in
`OcahAxiLiteSlaveSequence`.
"""

from __future__ import annotations

from cocotbext.axi import AxiLiteBus
from cocotbext.axi.axil_ram import AxiLiteRamRead, AxiLiteRamWrite
from cocotbext.axi.constants import AxiProt, AxiResp
from cocotbext.axi.memory import Memory

from .ocah_axi_slave_driver import OcahAxiResetGate, OcahFaultMixin

__all__ = ["OcahAxiLiteSlaveDriver"]


class _FaultAxiLiteRamWrite(AxiLiteRamWrite):
    def __init__(self, bus, clock, reset=None, reset_active_level=True, *, fault_owner, **kwargs):
        self.fault_owner = fault_owner
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)

    async def _process_write(self):
        while True:
            aw = await self.aw_channel.recv()
            addr = (int(aw.awaddr) // self.byte_lanes) * self.byte_lanes
            prot = AxiProt(int(getattr(aw, "awprot", AxiProt.NONSECURE)))
            w = await self.w_channel.recv()
            data = int(w.wdata).to_bytes(self.byte_lanes, "little")
            strb = (
                int(getattr(w, "wstrb", self.strb_mask)) if self.wstrb_present else self.strb_mask
            )
            b = self.b_channel._transaction_obj()
            b.bresp = self.fault_owner.write_errors.pop(addr, AxiResp.OKAY)

            if b.bresp == AxiResp.OKAY:
                start_offset = None
                for offset in range(self.byte_lanes + 1):
                    enabled = offset < self.byte_lanes and ((strb >> offset) & 0x1)
                    if enabled and start_offset is None:
                        start_offset = offset
                    if not enabled and start_offset is not None:
                        if offset != start_offset:
                            await self._write(addr + start_offset, data[start_offset:offset])
                        start_offset = None

            await self.b_channel.send(b)
            self.log.info(
                "AXI-Lite write addr=0x%08x awprot=%s strb=0x%x resp=%s",
                addr,
                prot,
                strb,
                AxiResp(b.bresp).name,
            )


class _FaultAxiLiteRamRead(AxiLiteRamRead):
    def __init__(self, bus, clock, reset=None, reset_active_level=True, *, fault_owner, **kwargs):
        self.fault_owner = fault_owner
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)

    async def _process_read(self):
        while True:
            ar = await self.ar_channel.recv()
            addr = (int(ar.araddr) // self.byte_lanes) * self.byte_lanes
            prot = AxiProt(int(getattr(ar, "arprot", AxiProt.NONSECURE)))
            r = self.r_channel._transaction_obj()
            r.rresp = self.fault_owner.read_errors.pop(addr, AxiResp.OKAY)
            data = (
                bytes(self.byte_lanes)
                if r.rresp != AxiResp.OKAY
                else await self._read(addr, self.byte_lanes)
            )
            r.rdata = int.from_bytes(data, "little")
            await self.r_channel.send(r)
            self.log.info(
                "AXI-Lite read addr=0x%08x arprot=%s resp=%s",
                addr,
                prot,
                AxiResp(r.rresp).name,
            )


class OcahAxiLiteSlaveDriver(Memory, OcahFaultMixin):
    """cocotbext AXI4-Lite RAM responder engine with OCAH fault-control APIs."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        size=2**64,
        mem=None,
        *,
        name="OcahAxiLiteSlaveDriver",
        **kwargs,
    ):
        self.write_if = None
        self.read_if = None
        self._init_fault_state(name)
        Memory.__init__(self, size, mem, **kwargs)
        self.write_if = _FaultAxiLiteRamWrite(
            bus.write,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=self.mem,
            fault_owner=self,
        )
        self.read_if = _FaultAxiLiteRamRead(
            bus.read,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=self.mem,
            fault_owner=self,
        )
        self.init_signals()
        self.reset_gate = OcahAxiResetGate(
            (
                self.write_if.aw_channel,
                self.write_if.w_channel,
                self.write_if.b_channel,
                self.read_if.ar_channel,
                self.read_if.r_channel,
            ),
            clock,
            reset,
            reset_active_level=reset_active_level,
            log=self.log,
        )

    def init_signals(self) -> None:
        """Drive the B/R payload signals to a deterministic 0 idle.

        Called at construction (and idempotent), so the response channels
        idle clean from the moment the responder exists — the backend
        otherwise initializes source payloads to X (``StreamSource._init_x``),
        which X-propagates into the DUT on 4-state simulators until the first
        response. Handshake signals stay owned by the backend, which already
        drives valid low at construction.
        """
        for channel in (self.write_if.b_channel, self.read_if.r_channel):
            handshake = {id(channel.valid), id(channel.ready)}
            for handle in channel.bus._signals.values():
                if id(handle) not in handshake:
                    handle.setimmediatevalue(0)

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, reset=None, **kwargs):
        return cls(AxiLiteBus.from_prefix(dut, prefix), clock, reset, **kwargs)
