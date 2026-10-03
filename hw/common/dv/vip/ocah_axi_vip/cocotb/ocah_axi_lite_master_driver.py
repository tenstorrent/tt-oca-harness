# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite master driver: the cocotbext-axi engine binding.

`OcahAxiLiteMasterDriver` owns the bus/clock/reset resolution and the
underlying ``cocotbext.axi.AxiLiteMaster`` instance, and exposes the
event-level ``init_write``/``init_read`` transaction starters plus the
cycle-level protocol-control engines behind ``write_skewed_result`` /
``read_hold_result`` (independent AW/W launch skew, deferred BREADY/RREADY)
and their two-outstanding forms ``write_pair_skewed_result`` /
``read_pair_hold_result`` (a second transaction queued behind the first
before its response is accepted, with the address channel's stall cycles and
stability observed at the wires), plus the scheduler behind
``pipeline_result`` (single-beat reads and writes in flight together, each
beat launched on its own cycle). The blocking, checked, result-returning
API lives in `OcahAxiLiteMasterSequence`.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles, Combine, First, ReadOnly, RisingEdge
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from cocotbext.axi.constants import AxiProt

__all__ = ["OcahAxiLiteMasterDriver", "OcahAxiPipelineTimeoutError"]


def _sample_int(handle) -> int:
    """Sample a signal as an int; absent handles and X resolve to 0."""
    if handle is None:
        return 0
    try:
        return int(handle.value)
    except ValueError:
        return 0


class _AxChannelWatch:
    """Per-cycle AW or AR channel observer for the two-outstanding operations.

    Counts the cycles VALID was held while READY was low (``stall_cycles``)
    and the completed handshakes, and reports whether every stalled beat kept
    VALID asserted with its address unchanged until READY (``stable``;
    IHI 0022 A3.2.1). Each sample is taken on a rising clock edge and reads
    the values of the cycle that just ended.
    """

    def __init__(self, clock, valid, ready, addr) -> None:
        self._clock = clock
        self._valid = valid
        self._ready = ready
        self._addr = addr
        self.stall_cycles = 0
        self.handshakes = 0
        self.stable = True
        self._pending_addr: int | None = None

    def sample(self) -> None:
        valid = _sample_int(self._valid)
        ready = _sample_int(self._ready)
        addr = _sample_int(self._addr)
        if valid and self._pending_addr is not None and addr != self._pending_addr:
            self.stable = False
        if valid and not ready:
            self._pending_addr = addr
            self.stall_cycles += 1
            return
        if valid and ready:
            self.handshakes += 1
        elif self._pending_addr is not None:
            self.stable = False
        self._pending_addr = None

    async def run(self) -> None:
        while True:
            await RisingEdge(self._clock)
            self.sample()


class _BeatLane:
    """Launch schedule of one request channel for ``pipeline``.

    ``dues[i]`` is the earliest cycle the i-th beat may launch. In the
    ReadOnly phase of every cycle the lane lets the backend source launch on
    the next edge only when the next unlaunched beat is due, so a beat leaves
    on the later of its due cycle and the acceptance of the beat ahead of it.
    """

    def __init__(self, clock, channel, valid, ready, dues: list[int]) -> None:
        self._clock = clock
        self._channel = channel
        self._valid = valid
        self._ready = ready
        self._dues = dues
        self.now = 0
        self.accepted = 0
        self.launched = 0

    def waiting(self) -> bool:
        """True while the next unlaunched beat is not yet due."""
        return self.launched < len(self._dues) and self._dues[self.launched] > self.now

    def arm(self) -> None:
        self._channel.pause = not (
            self.launched < len(self._dues) and self._dues[self.launched] <= self.now
        )

    async def run(self) -> None:
        while True:
            await RisingEdge(self._clock)
            self.now += 1
            if _sample_int(self._valid) and _sample_int(self._ready):
                self.accepted += 1
            await ReadOnly()
            self.launched = self.accepted + _sample_int(self._valid)
            self.arm()


class _ReadyHold:
    """Response-channel READY held low until ``cycles`` after the first VALID."""

    def __init__(self, clock, channel, valid, cycles: int) -> None:
        self._clock = clock
        self._channel = channel
        self._valid = valid
        self._cycles = int(cycles)
        self.counting = False
        self.released = self._cycles == 0

    def arm(self) -> None:
        self._channel.pause = not self.released

    async def run(self) -> None:
        if self.released:
            return
        while True:
            await RisingEdge(self._clock)
            if _sample_int(self._valid):
                break
        self.counting = True
        await ClockCycles(self._clock, self._cycles)
        await ReadOnly()
        self._channel.pause = False
        self.counting = False
        self.released = True


class OcahAxiPipelineTimeoutError(TimeoutError):
    """Expiry of ``pipeline``, carrying what it collected before the bound.

    ``raws`` holds one raw response per access in list order, ``None`` for an
    access whose response was not collected. The stall counters cover every
    cycle up to and including the one the bound expired on.
    """

    def __init__(
        self,
        message: str,
        *,
        raws: tuple,
        aw_stall_cycles: int,
        w_stall_cycles: int,
        ar_stall_cycles: int,
    ) -> None:
        super().__init__(message)
        self.raws = raws
        self.aw_stall_cycles = aw_stall_cycles
        self.w_stall_cycles = w_stall_cycles
        self.ar_stall_cycles = ar_stall_cycles


class OcahAxiLiteMasterDriver:
    """cocotbext-backed AXI4-Lite initiator engine for one bus connection."""

    def __init__(
        self,
        axi4_lite_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiLiteMaster",
        data_width: int = 32,
        reset_active_level: bool = False,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.data_width = data_width
        self.bytes_per_beat = data_width // 8
        self.full_strb = (1 << self.bytes_per_beat) - 1

        self.log = logging.getLogger(name)
        self._bus, self._clock, self._reset = self._resolve_bus_clock_reset(
            axi4_lite_intf,
            clock,
            reset,
        )
        self._master = AxiLiteMaster(
            self._bus,
            self._clock,
            self._reset,
            reset_active_level=reset_active_level,
            **kwargs,
        )
        self.init_signals()

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        **kwargs: Any,
    ) -> "OcahAxiLiteMasterDriver":
        """Construct from flattened AXI4-Lite signals using ``AxiLiteBus``."""
        return cls(AxiLiteBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    @staticmethod
    def _resolve_bus_clock_reset(axi4_lite_intf, clock, reset):
        if isinstance(axi4_lite_intf, AxiLiteBus):
            bus = axi4_lite_intf
        else:
            bus = AxiLiteBus.from_entity(axi4_lite_intf)

        resolved_clock = clock
        if resolved_clock is None:
            resolved_clock = getattr(axi4_lite_intf, "aclk", None)
        if resolved_clock is None:
            resolved_clock = getattr(axi4_lite_intf, "clk", None)
        if resolved_clock is None:
            raise ValueError(
                "OcahAxiLiteMasterDriver requires a clock or an interface with aclk/clk"
            )

        resolved_reset = reset
        if resolved_reset is None:
            resolved_reset = getattr(axi4_lite_intf, "aresetn", None)
        if resolved_reset is None:
            resolved_reset = getattr(axi4_lite_intf, "rst_ni", None)
        return bus, resolved_clock, resolved_reset

    def init_signals(self) -> None:
        """Drive the AW/W/AR payload signals to a deterministic 0 idle.

        Called at construction (and idempotent), so the bus idles clean from
        the moment the driver exists — the backend otherwise initializes
        source payloads to X (``StreamSource._init_x``), which X-propagates
        into the DUT on 4-state simulators until the first transaction.
        Handshake signals stay owned by the backend, which already drives
        valid low at construction.
        """
        for channel in (
            self._master.write_if.aw_channel,
            self._master.write_if.w_channel,
            self._master.read_if.ar_channel,
        ):
            handshake = {id(channel.valid), id(channel.ready)}
            for handle in channel.bus._signals.values():
                if id(handle) not in handshake:
                    handle.setimmediatevalue(0)

    async def wait_for_reset(self) -> None:
        """Wait until reset deassertion if a reset signal was provided."""
        if self._reset is None:
            return
        while int(self._reset.value) == 0:
            await RisingEdge(self._clock)

    @property
    def backend(self):
        """Return the underlying cocotbext ``AxiLiteMaster`` for debug only."""
        return self._master

    def init_write(
        self,
        address: int | None = None,
        data: int | bytes | bytearray = 0,
        *,
        addr: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        event=None,
    ):
        """Start a write and return the cocotb event, matching cocotbext style."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_write(
            target, self.data_bytes(data), prot=AxiProt(int(prot)), event=event
        )

    def init_read(
        self,
        address: int | None = None,
        length: int | None = None,
        *,
        addr: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        event=None,
    ):
        """Start a read and return the cocotb event, matching cocotbext style."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_read(
            target,
            self.bytes_per_beat if length is None else int(length),
            prot=AxiProt(int(prot)),
            event=event,
        )

    def data_bytes(self, data: int | bytes | bytearray) -> bytes:
        """Encode an integer beat as little-endian bytes (bytes pass through)."""
        if isinstance(data, int):
            mask = (1 << self.data_width) - 1
            return (data & mask).to_bytes(self.bytes_per_beat, "little")
        return bytes(data)

    def check_strb(self, strb: int | None) -> None:
        """Reject strobe patterns the cocotbext backend cannot honor."""
        self.strb_payload(0, strb)

    def strb_payload(self, data: int | bytes | bytearray, strb: int | None) -> tuple[int, bytes]:
        """Map a contiguous strobe onto a (byte offset, payload bytes) pair.

        The cocotbext backend derives WSTRB from the sub-word address and
        length of the payload, so any contiguous strobe is expressible as an
        offset write of the selected bytes of ``data``. Non-contiguous
        patterns have no such mapping and are rejected.
        """
        full = self.data_bytes(data)
        if strb is None or int(strb) == self.full_strb:
            return 0, full
        value = int(strb)
        if value == 0 or value & ~self.full_strb:
            raise ValueError(
                f"{self.name}: strb=0x{value:X} out of range for "
                f"{self.bytes_per_beat}-byte beats (full strobe 0x{self.full_strb:X})"
            )
        offset = (value & -value).bit_length() - 1
        span = value >> offset
        if span & (span + 1):
            raise ValueError(
                f"{self.name}: cocotbext AXI-Lite master supports contiguous strobes only; "
                f"got strb=0x{value:X}"
            )
        return offset, full[offset : offset + span.bit_length()]

    async def write_skewed(
        self,
        address: int,
        data: int | bytes | bytearray = 0,
        *,
        strb: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        aw_valid_delay: int = 0,
        w_valid_delay: int = 0,
        b_ready_delay: int = 0,
        timeout_cycles: int = 1000,
    ):
        """Single-beat write with independent AW/W launch skew; return the raw response.

        Mirrors the SV-UVM master's knobs: ``aw_valid_delay``/``w_valid_delay``
        hold that channel's VALID low for N cycles before it launches — AXI
        permits either arrival order — and ``b_ready_delay`` defers the BREADY
        assert after both request handshakes (BREADY idles low for the whole
        request phase). Requires an idle write engine, since the skew is
        applied by pausing its channels. Raises ``TimeoutError`` when a phase
        exceeds ``timeout_cycles``.
        """
        write_if = self._master.write_if
        if not write_if.idle():
            raise RuntimeError(f"{self.name}: write_skewed requires an idle write engine")
        offset, payload = self.strb_payload(data, strb)
        aw_channel = write_if.aw_channel
        w_channel = write_if.w_channel
        b_channel = write_if.b_channel
        aw_bus = self._bus.write.aw
        w_bus = self._bus.write.w
        aw_channel.pause = aw_valid_delay > 0
        w_channel.pause = w_valid_delay > 0
        b_channel.pause = True
        releases = []
        try:
            event = write_if.init_write(int(address) + offset, payload, prot=AxiProt(int(prot)))
            if aw_valid_delay > 0:
                releases.append(cocotb.start_soon(self._release_pause(aw_channel, aw_valid_delay)))
            if w_valid_delay > 0:
                releases.append(cocotb.start_soon(self._release_pause(w_channel, w_valid_delay)))
            aw_done = False
            w_done = False
            for _ in range(int(timeout_cycles)):
                await RisingEdge(self._clock)
                aw_done = aw_done or bool(
                    self._sample(aw_bus.awvalid) and self._sample(aw_bus.awready)
                )
                w_done = w_done or bool(self._sample(w_bus.wvalid) and self._sample(w_bus.wready))
                if aw_done and w_done:
                    break
            else:
                raise TimeoutError(
                    f"{self.name}: skewed write request phase timed out: addr=0x{int(address):08X} "
                    f"aw_done={aw_done} w_done={w_done}"
                )
            if b_ready_delay > 0:
                await ClockCycles(self._clock, int(b_ready_delay))
            b_channel.pause = False
            await First(event.wait(), ClockCycles(self._clock, int(timeout_cycles)))
            if not event.is_set():
                raise TimeoutError(
                    f"{self.name}: skewed write response timed out: addr=0x{int(address):08X}"
                )
            return event.data
        finally:
            for task in releases:
                task.cancel()
            aw_channel.pause = False
            w_channel.pause = False
            b_channel.pause = False

    async def read_hold(
        self,
        address: int,
        *,
        hold_cycles: int,
        prot: int = int(AxiProt.NONSECURE),
        timeout_cycles: int = 1000,
    ):
        """Single-beat read holding RREADY low for ``hold_cycles`` after RVALID.

        Returns ``(raw response, hold_stable)`` where ``hold_stable`` reports
        that RVALID stayed asserted with RDATA/RRESP unchanged across the hold
        window. Requires an idle read engine. Raises ``TimeoutError`` when a
        phase exceeds ``timeout_cycles``.
        """
        read_if = self._master.read_if
        if not read_if.idle():
            raise RuntimeError(f"{self.name}: read_hold requires an idle read engine")
        r_channel = read_if.r_channel
        r_bus = self._bus.read.r
        r_channel.pause = True
        try:
            event = read_if.init_read(int(address), self.bytes_per_beat, prot=AxiProt(int(prot)))
            for _ in range(int(timeout_cycles)):
                await RisingEdge(self._clock)
                if self._sample(r_bus.rvalid):
                    break
            else:
                raise TimeoutError(
                    f"{self.name}: held read saw no RVALID: addr=0x{int(address):08X}"
                )
            first_data = self._sample(r_bus.rdata)
            first_resp = self._sample(getattr(r_bus, "rresp", None))
            hold_stable = True
            for _ in range(int(hold_cycles)):
                await RisingEdge(self._clock)
                hold_stable = (
                    hold_stable
                    and bool(self._sample(r_bus.rvalid))
                    and self._sample(r_bus.rdata) == first_data
                    and self._sample(getattr(r_bus, "rresp", None)) == first_resp
                )
            r_channel.pause = False
            await First(event.wait(), ClockCycles(self._clock, int(timeout_cycles)))
            if not event.is_set():
                raise TimeoutError(
                    f"{self.name}: held read completion timed out: addr=0x{int(address):08X}"
                )
            return event.data, hold_stable
        finally:
            r_channel.pause = False

    async def write_pair_skewed(
        self,
        address_a: int,
        data_a: int | bytes | bytearray,
        address_b: int,
        data_b: int | bytes | bytearray,
        *,
        strb_a: int | None = None,
        strb_b: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        aw_valid_delay: int = 0,
        w_valid_delay: int = 0,
        b_ready_delay: int = 0,
        timeout_cycles: int = 1000,
    ):
        """Two single-beat writes queued back to back; return both raw responses.

        The AW and W of the second write queue behind the first on their
        channels, so under a W launch delay the second AW meets the responder
        while the first W is pending. The launch skew applies as in
        ``write_skewed`` (the channel pauses release once) and
        ``b_ready_delay`` defers BREADY after the first write's request
        phase, so a responder that admits one write in flight can retire
        the first B before the second W passes. Returns ``(raw_a, raw_b,
        aw_stall_cycles, aw_stable)`` from a per-cycle watch of the AW
        channel across both writes. Requires an idle write engine. Raises
        ``TimeoutError`` when a phase exceeds ``timeout_cycles``.
        """
        write_if = self._master.write_if
        if not write_if.idle():
            raise RuntimeError(f"{self.name}: write_pair_skewed requires an idle write engine")
        offset_a, payload_a = self.strb_payload(data_a, strb_a)
        offset_b, payload_b = self.strb_payload(data_b, strb_b)
        aw_channel = write_if.aw_channel
        w_channel = write_if.w_channel
        b_channel = write_if.b_channel
        aw_bus = self._bus.write.aw
        w_bus = self._bus.write.w
        watch = _AxChannelWatch(self._clock, aw_bus.awvalid, aw_bus.awready, aw_bus.awaddr)
        aw_channel.pause = aw_valid_delay > 0
        w_channel.pause = w_valid_delay > 0
        b_channel.pause = True
        releases = []
        try:
            event_a = write_if.init_write(
                int(address_a) + offset_a, payload_a, prot=AxiProt(int(prot))
            )
            event_b = write_if.init_write(
                int(address_b) + offset_b, payload_b, prot=AxiProt(int(prot))
            )
            if aw_valid_delay > 0:
                releases.append(cocotb.start_soon(self._release_pause(aw_channel, aw_valid_delay)))
            if w_valid_delay > 0:
                releases.append(cocotb.start_soon(self._release_pause(w_channel, w_valid_delay)))
            releases.append(cocotb.start_soon(watch.run()))
            aw_done = w_done = False
            for _ in range(int(timeout_cycles)):
                await RisingEdge(self._clock)
                aw_done = aw_done or bool(
                    self._sample(aw_bus.awvalid) and self._sample(aw_bus.awready)
                )
                w_done = w_done or bool(self._sample(w_bus.wvalid) and self._sample(w_bus.wready))
                if aw_done and w_done:
                    break
            else:
                raise TimeoutError(
                    f"{self.name}: paired write request phase timed out: "
                    f"a=0x{int(address_a):08X} b=0x{int(address_b):08X} "
                    f"aw_done={aw_done} w_done={w_done}"
                )
            if b_ready_delay > 0:
                await ClockCycles(self._clock, int(b_ready_delay))
            b_channel.pause = False
            await First(
                Combine(event_a.wait(), event_b.wait()),
                ClockCycles(self._clock, int(timeout_cycles)),
            )
            if not (event_a.is_set() and event_b.is_set()):
                raise TimeoutError(
                    f"{self.name}: paired write response timed out: "
                    f"a=0x{int(address_a):08X} b=0x{int(address_b):08X}"
                )
            return event_a.data, event_b.data, watch.stall_cycles, watch.stable
        finally:
            for task in releases:
                task.cancel()
            aw_channel.pause = False
            w_channel.pause = False
            b_channel.pause = False

    async def read_pair_hold(
        self,
        address_a: int,
        address_b: int,
        *,
        hold_cycles: int,
        prot: int = int(AxiProt.NONSECURE),
        timeout_cycles: int = 1000,
    ):
        """Two single-beat reads with the second AR presented while RREADY is held.

        AR(b) queues behind AR(a) on the address channel and RREADY stays
        low for ``hold_cycles`` after the first RVALID, so a responder that
        admits one read at a time holds AR(b) with ARREADY low until the
        first beat is accepted. Returns ``(raw_a, raw_b, hold_stable,
        ar_stall_cycles, ar_stable)``: the hold window's RVALID/RDATA/RRESP
        stability and the AR channel's stall count and stability from a
        per-cycle watch. Requires an idle read engine. Raises
        ``TimeoutError`` when a phase exceeds ``timeout_cycles``.
        """
        read_if = self._master.read_if
        if not read_if.idle():
            raise RuntimeError(f"{self.name}: read_pair_hold requires an idle read engine")
        r_channel = read_if.r_channel
        r_bus = self._bus.read.r
        ar_bus = self._bus.read.ar
        watch = _AxChannelWatch(self._clock, ar_bus.arvalid, ar_bus.arready, ar_bus.araddr)
        r_channel.pause = True
        try:
            event_a = read_if.init_read(
                int(address_a), self.bytes_per_beat, prot=AxiProt(int(prot))
            )
            event_b = read_if.init_read(
                int(address_b), self.bytes_per_beat, prot=AxiProt(int(prot))
            )
            for _ in range(int(timeout_cycles)):
                await RisingEdge(self._clock)
                watch.sample()
                if self._sample(r_bus.rvalid):
                    break
            else:
                raise TimeoutError(
                    f"{self.name}: paired read saw no RVALID: a=0x{int(address_a):08X}"
                )
            first_data = self._sample(r_bus.rdata)
            first_resp = self._sample(getattr(r_bus, "rresp", None))
            hold_stable = True
            for _ in range(int(hold_cycles)):
                await RisingEdge(self._clock)
                watch.sample()
                hold_stable = (
                    hold_stable
                    and bool(self._sample(r_bus.rvalid))
                    and self._sample(r_bus.rdata) == first_data
                    and self._sample(getattr(r_bus, "rresp", None)) == first_resp
                )
            r_channel.pause = False
            watch_task = cocotb.start_soon(watch.run())
            try:
                await First(
                    Combine(event_a.wait(), event_b.wait()),
                    ClockCycles(self._clock, int(timeout_cycles)),
                )
            finally:
                watch_task.cancel()
            if not (event_a.is_set() and event_b.is_set()):
                raise TimeoutError(
                    f"{self.name}: paired read completion timed out: "
                    f"a=0x{int(address_a):08X} b=0x{int(address_b):08X}"
                )
            return event_a.data, event_b.data, hold_stable, watch.stall_cycles, watch.stable
        finally:
            r_channel.pause = False

    async def pipeline(
        self,
        ops,
        *,
        b_hold_cycles: int = 0,
        r_hold_cycles: int = 0,
        timeout_cycles: int = 1000,
    ):
        """Single-beat reads and writes with several in flight; return the raw responses.

        ``ops`` is a sequence of ``OcahAxiPipelineOp``. Each beat launches no
        earlier than its channel delay, counted in cycles from the start, and
        no earlier than the acceptance of the previous beat on its channel;
        the read and write channels run independently. BREADY and RREADY stay
        low until ``b_hold_cycles`` and ``r_hold_cycles`` cycles after the
        first BVALID and RVALID, then accept every response in order. A read
        at an unaligned address asks for the bytes up to the end of its beat.
        Returns ``(raws, aw_stall_cycles, w_stall_cycles, ar_stall_cycles)``
        with ``raws`` in list order. Requires idle read and write engines.
        Every access is checked against the backend's address width,
        protection signals and strobe mapping before any is issued, so an
        invalid one raises ``ValueError`` with the bus untouched. Raises
        ``OcahAxiPipelineTimeoutError`` after ``timeout_cycles`` cycles with
        no handshake on any channel while no beat or READY hold is still
        waiting on its delay.
        """
        write_if = self._master.write_if
        read_if = self._master.read_if
        if not (write_if.idle() and read_if.idle()):
            raise RuntimeError(f"{self.name}: pipeline requires idle read and write engines")
        if not ops:
            raise ValueError(f"{self.name}: pipeline needs at least one access")
        writes = []
        reads = []
        for index, op in enumerate(ops):
            if op.direction == "write":
                offset, payload = self.strb_payload(op.data, op.strb)
                address = int(op.address) + offset
                length = len(payload)
                if address % self.bytes_per_beat + length > self.bytes_per_beat:
                    raise ValueError(
                        f"{self.name}: pipeline write at 0x{address:X} spans two beats"
                    )
                lane, engine, request = writes, write_if, payload
                prot_present = write_if.awprot_present
            elif op.direction == "read":
                address = int(op.address)
                length = self.bytes_per_beat - address % self.bytes_per_beat
                lane, engine, request = reads, read_if, length
                prot_present = read_if.arprot_present
            else:
                raise ValueError(f"{self.name}: unknown pipeline direction {op.direction!r}")
            where = f"{self.name}: pipeline {op.direction} {index} at {address:#x}"
            if address < 0 or address + length > 2**engine.address_width:
                raise ValueError(f"{where} leaves the {engine.address_width}-bit address space")
            prot = AxiProt.NONSECURE if op.prot is None else op.prot
            if not (isinstance(prot, int) and 0 <= prot <= 7):
                raise ValueError(f"{where} has prot={prot!r}; AxiProt takes 0 to 7")
            if prot != AxiProt.NONSECURE and not prot_present:
                raise ValueError(f"{where} sets prot={prot} on a bus without a protection signal")
            delays = (op.aw_valid_delay, op.w_valid_delay, op.ar_valid_delay)
            if not all(isinstance(delay, int) and delay >= 0 for delay in delays):
                raise ValueError(f"{where} has delays {delays}; each must be a non-negative int")
            lane.append((index, address, request, AxiProt(prot), op))

        aw_bus = self._bus.write.aw
        w_bus = self._bus.write.w
        b_bus = self._bus.write.b
        ar_bus = self._bus.read.ar
        r_bus = self._bus.read.r
        sources = (write_if.aw_channel, write_if.w_channel, read_if.ar_channel)
        limits = [source.queue_occupancy_limit for source in sources]
        requests = (
            (aw_bus.awvalid, aw_bus.awready),
            (w_bus.wvalid, w_bus.wready),
            (ar_bus.arvalid, ar_bus.arready),
        )
        responses = ((b_bus.bvalid, b_bus.bready), (r_bus.rvalid, r_bus.rready))
        tasks = []
        try:
            lanes = (
                _BeatLane(
                    self._clock,
                    write_if.aw_channel,
                    aw_bus.awvalid,
                    aw_bus.awready,
                    [op.aw_valid_delay for *_, op in writes],
                ),
                _BeatLane(
                    self._clock,
                    write_if.w_channel,
                    w_bus.wvalid,
                    w_bus.wready,
                    [op.w_valid_delay for *_, op in writes],
                ),
                _BeatLane(
                    self._clock,
                    read_if.ar_channel,
                    ar_bus.arvalid,
                    ar_bus.arready,
                    [op.ar_valid_delay for *_, op in reads],
                ),
            )
            holds = (
                _ReadyHold(self._clock, write_if.b_channel, b_bus.bvalid, b_hold_cycles),
                _ReadyHold(self._clock, read_if.r_channel, r_bus.rvalid, r_hold_cycles),
            )
            for source in sources:
                source.queue_occupancy_limit = -1
            for gate in (*lanes, *holds):
                gate.arm()
            events = [None] * len(ops)
            for index, address, payload, prot, _ in writes:
                events[index] = write_if.init_write(address, payload, prot=prot)
            for index, address, length, prot, _ in reads:
                events[index] = read_if.init_read(address, length, prot=prot)
            tasks = [cocotb.start_soon(gate.run()) for gate in (*lanes, *holds)]
            stalls = [0, 0, 0]
            idle = 0
            while not all(event.is_set() for event in events):
                await RisingEdge(self._clock)
                for channel, (valid, ready) in enumerate(requests):
                    if self._sample(valid) and not self._sample(ready):
                        stalls[channel] += 1
                moved = any(self._sample(v) and self._sample(r) for v, r in (*requests, *responses))
                waiting = any(lane.waiting() for lane in lanes) or any(
                    hold.counting for hold in holds
                )
                idle = 0 if (moved or waiting) else idle + 1
                if idle >= int(timeout_cycles):
                    done = sum(event.is_set() for event in events)
                    raise OcahAxiPipelineTimeoutError(
                        f"{self.name}: pipeline stalled with {done}/{len(ops)} accesses complete",
                        raws=tuple(event.data if event.is_set() else None for event in events),
                        aw_stall_cycles=stalls[0],
                        w_stall_cycles=stalls[1],
                        ar_stall_cycles=stalls[2],
                    )
            return (tuple(event.data for event in events), *stalls)
        finally:
            for task in tasks:
                task.cancel()
            for source, limit in zip(sources, limits):
                source.queue_occupancy_limit = limit
                source.pause = False
            write_if.b_channel.pause = False
            read_if.r_channel.pause = False

    async def _release_pause(self, channel, cycles: int) -> None:
        """Drop a channel's pause after ``cycles`` clock edges.

        The release lands in the ReadOnly phase, after the channel's own
        edge evaluation, so the launch happens on the following edge and the
        observed skew is never shorter than requested.
        """
        await ClockCycles(self._clock, int(cycles))
        await ReadOnly()
        channel.pause = False

    @staticmethod
    def _sample(handle) -> int:
        """Sample a signal as an int; absent handles and X resolve to 0."""
        return _sample_int(handle)

    @staticmethod
    def _coalesce_addr(address: int | None, addr: int | None) -> int:
        if address is None and addr is None:
            raise TypeError("address or addr is required")
        if address is not None and addr is not None and int(address) != int(addr):
            raise ValueError(f"conflicting address={address} and addr={addr}")
        return int(address if address is not None else addr)
