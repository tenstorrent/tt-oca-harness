# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 slave driver: fault-capable memory-backed responder engine.

`OcahAxiSlaveDriver` is the cocotbext-backed RAM responder that answers AXI4
traffic on the wires, extended with the OCAH fault controls (one-shot
non-OKAY response injection and bounded READY backpressure) shared through
`OcahFaultMixin`. The test-facing backdoor/fault API lives in
`OcahAxiSlaveSequence`; the AXI4-Lite variant lives in
`ocah_axi_lite_slave_driver.py` and reuses the mixin and the reset gate from
here.

The responder exists from construction so its READY signals are driven from
time zero, and `OcahAxiResetGate` keeps its cocotbext channel endpoints parked
until the reset input reads a defined inactive level: on a 4-state simulator
the DUT's request handshakes are X until its reset has propagated, and the
endpoints convert a sampled handshake with ``bool()``, which raises on X. An
X handshake after the release raises in the engine: it is a DUT defect.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable, Iterator
from typing import Any

import cocotb
from cocotb.task import Task
from cocotb.triggers import ClockCycles, Event, Lock, RisingEdge
from cocotbext.axi import AxiBus
from cocotbext.axi.axi_ram import AxiRamRead, AxiRamWrite
from cocotbext.axi.constants import AxiBurstType, AxiProt, AxiResp
from cocotbext.axi.memory import Memory

__all__ = ["OcahAxiResetGate", "OcahAxiSlaveDriver", "OcahFaultMixin"]


def _pause_pattern(stall_cycles: int):
    """Continuously insert bounded READY stalls without risking a permanent hang."""
    while True:
        for _ in range(max(stall_cycles, 0)):
            yield True
        yield False


class OcahAxiResetGate:
    """Holds cocotbext stream endpoints in their local reset until the reset input is inactive.

    A cocotbext endpoint treats itself as out of reset at construction and
    follows only later edges of its reset input, so one built before the bench
    drives that input samples the DUT's handshakes at the first clock edge.
    The gate asserts every endpoint's local reset at construction (READY and
    VALID driven 0, sampling loops stopped) and releases it on the first clock
    edge at which the reset input is resolvable and at its inactive level.
    Without a reset input the endpoints run from construction.
    """

    def __init__(
        self,
        endpoints: Iterable[Any],
        clock: Any,
        reset: Any,
        *,
        reset_active_level: bool,
        log: logging.Logger,
    ) -> None:
        self._endpoints = tuple(endpoints)
        self._clock = clock
        self._reset = reset
        self._reset_active_level = bool(reset_active_level)
        self._log = log
        self._task: Task | None = None
        if reset is None:
            return
        for endpoint in self._endpoints:
            endpoint.assert_reset(True)
        self._task = cocotb.start_soon(self._release_when_inactive())

    @property
    def is_released(self) -> bool:
        """True once the endpoints follow the reset input on their own."""
        return self._task is None

    def cancel(self) -> None:
        """Stop waiting for the reset input; the endpoints stay as they are."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _release_when_inactive(self) -> None:
        while True:
            await RisingEdge(self._clock)
            level = self._reset.value
            if level.is_resolvable and bool(int(level)) != self._reset_active_level:
                break
        for endpoint in self._endpoints:
            endpoint.assert_reset(False)
        self._task = None
        self._log.debug("reset input inactive: %d endpoints released", len(self._endpoints))


class OcahFaultMixin:
    """Shared one-shot response injection and READY backpressure API."""

    def _init_fault_state(self, name: str) -> None:
        self.write_errors: dict[int, AxiResp] = {}
        self.read_errors: dict[int, AxiResp] = {}
        self.write_id_corrupt: int | None = None
        self.read_id_corrupt: int | None = None
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

    def inject_id_corruption(
        self,
        *,
        mask: int = 0x1,
        read: bool = True,
        write: bool = True,
    ) -> None:
        """Arm one-shot response-ID corruption (BID/RID XOR ``mask``).

        The next selected transaction answers with ``request_id ^ mask``
        (truncated to the ID signal width) instead of echoing the request ID,
        so ID-observing masters can prove a wrong returned ID is
        distinguishable from the issued one.  One-shot per direction;
        ``clear_errors()`` disarms.
        """
        if int(mask) == 0:
            raise ValueError("inject_id_corruption mask must be non-zero")
        if write:
            self.write_id_corrupt = int(mask)
        if read:
            self.read_id_corrupt = int(mask)
        self.log.info(
            "Injecting AXI response-ID corruption mask=0x%x read=%d write=%d",
            mask,
            read,
            write,
        )

    def clear_errors(self) -> None:
        self.write_errors.clear()
        self.read_errors.clear()
        self.write_id_corrupt = None
        self.read_id_corrupt = None

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


class _OutstandingWindow:
    """The transactions one direction of the responder holds between request and response.

    With no depth the responder serves one request at a time, as the cocotbext
    engine does: its request queue holds two more, and each response is sent
    before the next request is taken. With a depth, the request sink takes a
    request only while fewer than ``depth`` are outstanding, counted from the
    address handshake to the B handshake or the RLAST handshake, and each
    response runs as its own task: it waits its response delay, then for the
    previous response of the same ID, so same-ID responses leave in request
    order while different IDs overtake one another.
    """

    def __init__(
        self,
        request: Any,
        response: Any,
        clock: Any,
        depth: int | None,
        *,
        buffers: Iterable[Any] = (),
        last: Any = None,
    ) -> None:
        if depth is not None and int(depth) < 1:
            raise ValueError(f"max_outstanding must be >= 1, got {depth}")
        self.depth = None if depth is None else int(depth)
        self.delays: Iterator[int] | None = None
        self.peak = 0
        self._request = request
        self._response = response
        self._clock = clock
        self._last = last
        self._taken = 0
        self._retired = 0
        self._tails: dict[int, Event] = {}
        self._tasks: set[Task] = set()
        if self.depth is None:
            return
        for channel in (request, response, *buffers):
            channel.queue_occupancy_limit = self.depth
        # The sink decides READY from full() at every clock edge after taking
        # that edge's handshake, so a request is accepted only while the
        # window has room, whether it waits in the queue or is in service.
        request.full = self._full
        cocotb.start_soon(self._count_retirements())

    @property
    def concurrent(self) -> bool:
        return self.depth is not None

    def outstanding(self) -> int:
        return self._taken + self._request.count() - self._retired

    def _full(self) -> bool:
        occupancy = self.outstanding()
        self.peak = max(self.peak, occupancy)
        return occupancy >= self.depth

    def take(self) -> None:
        """Count a request taken from the sink queue into service."""
        self._taken += 1

    def next_delay(self) -> int:
        if self.delays is None:
            return 0
        return max(int(next(self.delays, 0)), 0)

    async def respond(self, request_id: int, send: Callable[[], Awaitable[None]]) -> None:
        """Send one response after its delay, behind any earlier response of ``request_id``."""
        delay = self.next_delay()
        if not self.concurrent:
            if delay:
                await ClockCycles(self._clock, delay)
            await send()
            return
        previous = self._tails.get(request_id)
        done = Event()
        self._tails[request_id] = done
        self._tasks = {task for task in self._tasks if not task.done()}
        self._tasks.add(cocotb.start_soon(self._ordered(request_id, previous, done, delay, send)))

    async def _ordered(
        self,
        request_id: int,
        previous: Event | None,
        done: Event,
        delay: int,
        send: Callable[[], Awaitable[None]],
    ) -> None:
        if delay:
            await ClockCycles(self._clock, delay)
        if previous is not None:
            await previous.wait()
        await send()
        done.set()
        if self._tails.get(request_id) is done:
            del self._tails[request_id]

    async def _count_retirements(self) -> None:
        valid = self._response.valid
        ready = self._response.ready
        while True:
            await RisingEdge(self._clock)
            if not (_is_high(valid) and _is_high(ready)):
                continue
            if self._last is not None and not _is_high(self._last):
                continue
            self._retired += 1
            self._request.wake_event.set()

    def reset(self) -> None:
        """Drop every response in service; the sink queues are cleared by the engine."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._tails.clear()
        self._taken = 0
        self._retired = 0


def _is_high(handle: Any) -> bool:
    value = handle.value
    return value.is_resolvable and bool(int(value))


class _FaultAxiRamWrite(AxiRamWrite):
    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        *,
        fault_owner,
        max_outstanding=None,
        **kwargs,
    ):
        self.fault_owner = fault_owner
        self.window: _OutstandingWindow | None = None
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)
        try:
            self._bid_mask = (1 << len(self.bus.b.bid)) - 1
        except (AttributeError, TypeError):
            self._bid_mask = None
        self.window = _OutstandingWindow(
            self.aw_channel,
            self.b_channel,
            clock,
            max_outstanding,
            buffers=(self.w_channel,),
        )

    def _handle_reset(self, state):
        if state and self.window is not None:
            self.window.reset()
        super()._handle_reset(state)

    async def _process_write(self):
        while True:
            aw = await self.aw_channel.recv()
            self.window.take()
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

            # One-shot armed BID corruption: answer with a wrong response ID
            # (data path and BRESP stay untouched).
            id_corrupt = self.fault_owner.write_id_corrupt
            if id_corrupt is not None:
                self.fault_owner.write_id_corrupt = None
                corrupted = awid ^ id_corrupt
                if self._bid_mask is not None:
                    corrupted &= self._bid_mask
                b.bid = corrupted
                self.log.info(
                    "Corrupting BID awid=0x%x -> bid=0x%x (mask=0x%x)",
                    awid,
                    corrupted,
                    id_corrupt,
                )

            # W beats carry no ID and arrive in AW order, so they are taken
            # here, in request order; only the B response is deferred.
            for beat in range(beats):
                cur_word_addr = (cur_addr // self.byte_lanes) * self.byte_lanes
                w = await self.w_channel.recv()
                strb = (
                    int(getattr(w, "wstrb", self.strb_mask))
                    if self.wstrb_present
                    else self.strb_mask
                )
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
                                await self._write(
                                    cur_word_addr + start_offset, data[start_offset:offset]
                                )
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

            await self.window.respond(awid, lambda b=b: self.b_channel.send(b))


class _FaultAxiRamRead(AxiRamRead):
    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        *,
        fault_owner,
        max_outstanding=None,
        **kwargs,
    ):
        self.fault_owner = fault_owner
        self.window: _OutstandingWindow | None = None
        super().__init__(bus, clock, reset, reset_active_level=reset_active_level, **kwargs)
        try:
            self._rid_mask = (1 << len(self.bus.r.rid)) - 1
        except (AttributeError, TypeError):
            self._rid_mask = None
        # Bursts of different IDs are not interleaved beat by beat on R.
        self._r_lock = Lock()
        self.window = _OutstandingWindow(
            self.ar_channel,
            self.r_channel,
            clock,
            max_outstanding,
            last=getattr(self.r_channel.bus, "rlast", None),
        )

    def _handle_reset(self, state):
        if state and self.window is not None:
            self.window.reset()
            self._r_lock = Lock()
        super()._handle_reset(state)

    async def _process_read(self):
        while True:
            ar = await self.ar_channel.recv()
            self.window.take()
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

            # One-shot armed RID corruption applies to every beat of this one
            # transaction (data path and RRESP stay untouched).
            rid = arid
            id_corrupt = self.fault_owner.read_id_corrupt
            if id_corrupt is not None:
                self.fault_owner.read_id_corrupt = None
                rid = arid ^ id_corrupt
                if self._rid_mask is not None:
                    rid &= self._rid_mask
                self.log.info(
                    "Corrupting RID arid=0x%x -> rid=0x%x (mask=0x%x)",
                    arid,
                    rid,
                    id_corrupt,
                )

            # One-shot errors are claimed here, in request order, however late
            # the response is sent.
            plan = []
            for _ in range(beats):
                cur_word_addr = (cur_addr // self.byte_lanes) * self.byte_lanes
                plan.append(
                    (cur_word_addr, self.fault_owner.read_errors.pop(cur_word_addr, AxiResp.OKAY))
                )
                if burst != AxiBurstType.FIXED:
                    cur_addr += num_bytes
                    if burst == AxiBurstType.WRAP and cur_addr == upper_wrap_boundary:
                        cur_addr = lower_wrap_boundary

            await self.window.respond(
                arid, lambda rid=rid, plan=plan, prot=prot: self._send_burst(rid, plan, prot)
            )

    async def _send_burst(self, rid: int, plan: list[tuple[int, AxiResp]], prot: AxiProt) -> None:
        async with self._r_lock:
            for beat, (word_addr, resp) in enumerate(plan):
                r = self.r_channel._transaction_obj()
                r.rid = rid
                r.rlast = beat == len(plan) - 1
                r.rresp = resp
                data = (
                    bytes(self.byte_lanes)
                    if resp != AxiResp.OKAY
                    else await self._read(word_addr, self.byte_lanes)
                )
                r.rdata = int.from_bytes(data, "little")
                await self.r_channel.send(r)
                self.log.info(
                    "Read beat araddr=0x%08x arprot=%s resp=%s",
                    word_addr,
                    prot,
                    AxiResp(resp).name,
                )


class OcahAxiSlaveDriver(Memory, OcahFaultMixin):
    """cocotbext AXI4 RAM responder engine with OCAH fault-control APIs."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        reset_active_level=True,
        size=2**64,
        mem=None,
        *,
        name="OcahAxiSlaveDriver",
        max_outstanding: int | None = None,
        **kwargs,
    ):
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
            max_outstanding=max_outstanding,
        )
        self.read_if = _FaultAxiRamRead(
            bus.read,
            clock,
            reset,
            reset_active_level=reset_active_level,
            size=size,
            mem=self.mem,
            fault_owner=self,
            max_outstanding=max_outstanding,
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

    @property
    def max_outstanding(self) -> int | None:
        """Outstanding depth per direction, or ``None`` for one request served at a time."""
        return self.write_if.window.depth

    def set_response_delay(
        self, delays: int | Iterable[int], *, read: bool = True, write: bool = True
    ) -> None:
        """Delay each response by the next value of ``delays``, in clock cycles.

        An integer delays every response by that many cycles; an iterable is
        drawn once per response in request order, and responses after it is
        exhausted are not delayed. With a depth set, a delayed response holds
        back only later responses of its own ID.
        """
        for selected, window in ((write, self.write_if.window), (read, self.read_if.window)):
            if selected:
                window.delays = (
                    itertools.repeat(int(delays)) if isinstance(delays, int) else iter(delays)
                )
        self.log.info("Response delay set read=%d write=%d", read, write)

    def clear_response_delay(self) -> None:
        self.write_if.window.delays = None
        self.read_if.window.delays = None

    def outstanding_peak(self) -> dict[str, int]:
        """Most write and read transactions outstanding at once since construction."""
        if self.max_outstanding is None:
            raise RuntimeError("outstanding occupancy is tracked only with max_outstanding set")
        return {"write": self.write_if.window.peak, "read": self.read_if.window.peak}

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
        return cls(AxiBus.from_prefix(dut, prefix), clock, reset, **kwargs)
