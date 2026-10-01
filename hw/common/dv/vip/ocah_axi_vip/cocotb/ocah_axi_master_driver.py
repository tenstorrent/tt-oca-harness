# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 master driver: the cocotbext-axi engine binding.

`OcahAxiMasterDriver` owns the bus/clock/reset resolution and the underlying
``cocotbext.axi.AxiMaster`` instance, and exposes the event-level
``init_write``/``init_read`` transaction starters. The blocking, checked,
result-returning API lives in `OcahAxiMasterSequence` — the VIP's test-facing
surface — which wraps one driver.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from cocotb.triggers import RisingEdge
from cocotbext.axi import AxiBus, AxiMaster
from cocotbext.axi.constants import AxiBurstType, AxiLockType, AxiProt

from .ocah_axi_master_config import AxiTimingProfile

__all__ = ["OcahAxiMasterDriver", "OcahAxiIdCapture", "apply_profile", "clear_profile"]


class OcahAxiIdCapture:
    """Live response-ID watcher for one blocking transaction.

    Samples the ID signal of a response channel (B or R) on its live
    valid/ready handshake, independently of anything the backend reports —
    never a copy of the issued ID, so a responder that echoes the wrong ID
    is distinguishable.  For reads the ID is taken on the completing (RLAST)
    beat; for writes on the single B beat.

    The watcher never raises into the test: an unresolvable (X/Z) ID on a
    completing beat, a missing ID signal, or no completing beat all yield a
    capture miss (``finish()`` returns ``None``). A miss is ``None``, not a
    warning — the test owns the verdict.

    Capture is scoped to one blocking transaction: it samples the first
    completing beat between ``start_response_id_capture()`` and
    ``finish()``, which is this transaction's beat whenever the caller
    serializes transactions (the normal use of the blocking result API).
    """

    def __init__(self, *, clock, valid, ready, id_signal, last, log, label: str) -> None:
        self._clock = clock
        self._log = log
        self._label = label
        self._captured: int | None = None
        self._task = None
        if clock is None or valid is None or ready is None or id_signal is None:
            return
        self._task = cocotb.start_soon(self._watch(valid, ready, id_signal, last))

    async def _watch(self, valid, ready, id_signal, last) -> None:
        while True:
            await RisingEdge(self._clock)
            try:
                if int(valid.value) == 0 or int(ready.value) == 0:
                    continue
            except ValueError:
                continue
            try:
                sampled = int(id_signal.value)
            except ValueError:
                if last is None:
                    return
                try:
                    if int(last.value) == 1:
                        return
                except ValueError:
                    return
                continue
            if last is None:
                self._captured = sampled
                return
            try:
                if int(last.value) == 1:
                    self._captured = sampled
                    return
            except ValueError:
                return

    def cancel(self) -> None:
        """Stop watching without waiting (timeout/error paths)."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None

    async def finish(self, *, grace_cycles: int = 8) -> int | None:
        """Return the sampled ID, allowing a short grace window to land.

        The backend completes a transaction in the same simulation step as
        the final handshake, so the watcher normally finishes first; the
        grace window covers scheduling-order skew only.
        """
        if self._task is None:
            return None
        for _ in range(grace_cycles):
            if self._task.done():
                break
            await RisingEdge(self._clock)
        if not self._task.done():
            self._task.cancel()
            self._task = None
            return None
        self._task = None
        return self._captured


class OcahAxiMasterDriver:
    """cocotbext-backed AXI4 initiator engine for one bus connection."""

    def __init__(
        self,
        axi4_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiMaster",
        addr_width: int = 32,
        data_width: int = 32,
        reset_active_level: bool = False,
        max_burst_len: int = 256,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.addr_width = addr_width
        self.data_width = data_width
        self._bytes_per_beat = data_width // 8
        self._full_strb = (1 << self._bytes_per_beat) - 1

        self.log = logging.getLogger(name)
        self._bus, self._clock, self._reset = self._resolve_bus_clock_reset(axi4_intf, clock, reset)
        timing = kwargs.pop("timing", None)
        self._master = AxiMaster(
            self._bus,
            self._clock,
            self._reset,
            reset_active_level=reset_active_level,
            max_burst_len=max_burst_len,
            **kwargs,
        )
        self.init_signals()
        if timing is not None:
            self.set_timing(timing)

    @classmethod
    def from_prefix(
        cls, dut, prefix: str, clock, reset=None, **kwargs: Any
    ) -> "OcahAxiMasterDriver":
        """Construct from flattened AXI4 signals using ``AxiBus``."""
        return cls(AxiBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    @staticmethod
    def _resolve_bus_clock_reset(axi4_intf, clock, reset):
        if isinstance(axi4_intf, AxiBus):
            bus = axi4_intf
        else:
            bus = AxiBus.from_entity(axi4_intf)

        resolved_clock = clock
        if resolved_clock is None:
            resolved_clock = getattr(axi4_intf, "aclk", None)
        if resolved_clock is None:
            resolved_clock = getattr(axi4_intf, "clk", None)
        if resolved_clock is None:
            raise ValueError("OcahAxiMasterDriver requires a clock or an interface with aclk/clk")

        resolved_reset = reset
        if resolved_reset is None:
            resolved_reset = getattr(axi4_intf, "aresetn", None)
        if resolved_reset is None:
            resolved_reset = getattr(axi4_intf, "rst_ni", None)
        return bus, resolved_clock, resolved_reset

    def set_timing(self, profile: AxiTimingProfile) -> None:
        """Arm an ``AxiTimingProfile`` on this master's five channels.

        AXI channels are independent, so AW/W ordering and response-channel
        backpressure are legal stimulus the backend cannot otherwise produce.
        See ``AxiTimingProfile`` in ocah_axi_master_config.
        """
        apply_profile(self, profile)

    @property
    def channels(self) -> dict:
        """The backend channel objects, keyed by AxiTimingProfile field name.

        Exposed so timing control does not reach into the backend handle.
        """
        return {
            "aw_delay": self._master.write_if.aw_channel,
            "w_delay": self._master.write_if.w_channel,
            "ar_delay": self._master.read_if.ar_channel,
            "b_ready_delay": self._master.write_if.b_channel,
            "r_ready_delay": self._master.read_if.r_channel,
        }

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
        from cocotb.triggers import RisingEdge

        while int(self._reset.value) == 0:
            await RisingEdge(self._clock)

    @property
    def backend(self):
        """Return the underlying cocotbext ``AxiMaster`` for debug only."""
        return self._master

    def start_response_id_capture(self, channel: str) -> OcahAxiIdCapture:
        """Start a live BID/RID watcher for the next blocking transaction.

        ``channel`` is ``"b"`` (write response) or ``"r"`` (read data).  On a
        bus without ID signals (AXI4-Lite-shaped connections) the capture is
        inert and ``finish()`` returns ``None``.
        """
        if channel == "b":
            bus = self._bus.write.b
            valid = getattr(bus, "bvalid", None)
            ready = getattr(bus, "bready", None)
            id_signal = getattr(bus, "bid", None)
            last = None
            label = f"{self.name}: BID"
        elif channel == "r":
            bus = self._bus.read.r
            valid = getattr(bus, "rvalid", None)
            ready = getattr(bus, "rready", None)
            id_signal = getattr(bus, "rid", None)
            last = getattr(bus, "rlast", None)
            label = f"{self.name}: RID"
        else:
            raise ValueError(f"{self.name}: unknown response channel {channel!r}")
        return OcahAxiIdCapture(
            clock=self._clock,
            valid=valid,
            ready=ready,
            id_signal=id_signal,
            last=last,
            log=self.log,
            label=label,
        )

    def init_write(
        self,
        address: int | None = None,
        data: int | bytes | bytearray = 0,
        *,
        addr: int | None = None,
        awid: int | None = None,
        id: int | None = None,
        burst: int = int(AxiBurstType.INCR),
        size: int | None = None,
        lock: int = int(AxiLockType.NORMAL),
        cache: int = 0b0011,
        prot: int = int(AxiProt.NONSECURE),
        qos: int = 0,
        region: int = 0,
        user: int = 0,
        wuser=None,
        event=None,
    ):
        """Start a write and return the cocotb event."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_write(
            target,
            self.data_bytes(data, size=size),
            awid=self._coalesce_id(awid, id),
            burst=AxiBurstType(int(burst)),
            size=size,
            lock=AxiLockType(int(lock)),
            cache=cache,
            prot=AxiProt(int(prot)),
            qos=qos,
            region=region,
            user=user,
            wuser=wuser,
            event=event,
        )

    def init_read(
        self,
        address: int | None = None,
        length: int | None = None,
        *,
        addr: int | None = None,
        arid: int | None = None,
        id: int | None = None,
        burst: int = int(AxiBurstType.INCR),
        size: int | None = None,
        lock: int = int(AxiLockType.NORMAL),
        cache: int = 0b0011,
        prot: int = int(AxiProt.NONSECURE),
        qos: int = 0,
        region: int = 0,
        user: int = 0,
        event=None,
    ):
        """Start a read and return the cocotb event."""
        target = self._coalesce_addr(address, addr)
        transfer_length = self.bytes_for_beats(1, size) if length is None else int(length)
        return self._master.init_read(
            target,
            transfer_length,
            arid=self._coalesce_id(arid, id),
            burst=AxiBurstType(int(burst)),
            size=size,
            lock=AxiLockType(int(lock)),
            cache=cache,
            prot=AxiProt(int(prot)),
            qos=qos,
            region=region,
            user=user,
            event=event,
        )

    def data_bytes(self, data: int | bytes | bytearray, *, size: int | None) -> bytes:
        """Encode an integer beat as little-endian bytes (bytes pass through)."""
        if isinstance(data, int):
            beat_bytes = self.bytes_for_beats(1, size)
            return (data & ((1 << (8 * beat_bytes)) - 1)).to_bytes(beat_bytes, "little")
        return bytes(data)

    def bytes_for_beats(self, beats: int, size: int | None) -> int:
        """Total transfer bytes for ``beats`` beats at AxSIZE ``size``."""
        beat_bytes = self._bytes_per_beat if size is None else 2 ** int(size)
        return beats * beat_bytes

    def check_strb(self, strb: int | None, size: int | None) -> None:
        """Reject partial strobes the cocotbext backend cannot honor."""
        beat_bytes = self.bytes_for_beats(1, size)
        full_strb = (1 << beat_bytes) - 1
        if strb is not None and int(strb) != full_strb:
            raise ValueError(
                f"{self.name}: cocotbext AXI master supports contiguous writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{full_strb:X}"
            )

    @staticmethod
    def _coalesce_addr(address: int | None, addr: int | None) -> int:
        if address is None and addr is None:
            raise TypeError("address or addr is required")
        if address is not None and addr is not None and int(address) != int(addr):
            raise ValueError(f"conflicting address={address} and addr={addr}")
        return int(address if address is not None else addr)

    @staticmethod
    def _coalesce_id(primary: int | None, alias: int | None) -> int | None:
        if primary is not None and alias is not None and int(primary) != int(alias):
            raise ValueError(f"conflicting AXI IDs {primary} and {alias}")
        value = primary if primary is not None else alias
        return None if value is None else int(value)


def _hold_then_go(cycles: int):
    """Pause generator: hold the channel for ``cycles`` edges, then release.

    The backend advances one value per clock edge from the moment the
    generator is armed, so this counts from arming. That suits a response
    channel, whose delay is plain backpressure and orders against nothing. The
    write channels order against each other and use _release_on_leader_valid
    instead.

    It never StopIterations, because a generator that ends leaves the channel
    at its last value.
    """
    for _ in range(cycles):
        yield True
    while True:
        yield False


# Pending release per channel. A profile armed while an earlier release is
# still waiting would have that release clear the pause it just set, so the
# previous one is cancelled first.
_OCAH_RELEASERS: dict = {}


def _is_high(sig) -> bool:
    """True only when ``sig`` resolves to 1.

    The handle value renders as a single character, and anything that is not
    "1" -- including X and Z before the driver is up -- is not a VALID
    assertion.
    """
    return str(sig.value) == "1"


async def _release_on_leader_valid(trailing, leading, cycles: int) -> None:
    """Hold ``trailing`` until ``leading`` asserts VALID, then ``cycles`` more.

    VALID assertion is the only event that orders the channels. A cycle count
    runs from when the profile is armed, which is spent before the write is
    issued. The leading queue empties in the same delta its beat is driven, so
    a queue-drained release fires too late to have held anything. The leading
    handshake waits on the slave, and one that holds WREADY until AW can never
    grant a W-first handshake, so a handshake-driven release deadlocks that
    ordering.
    """
    edge = RisingEdge(trailing.clock)
    while True:
        await edge
        if leading.valid is not None and _is_high(leading.valid):
            break
    for _ in range(cycles):
        await edge
    trailing.pause = False


def apply_profile(driver, profile: AxiTimingProfile) -> None:
    """Arm ``profile`` on ``driver``'s channels.

    Channels with a zero delay are actively cleared rather than left alone, so
    applying a profile fully replaces the previous one instead of merging with
    it.
    """
    for chan in driver.channels.values():
        task = _OCAH_RELEASERS.pop(chan, None)
        if task is not None:
            task.kill()

    chans = driver.channels
    # AW and W order against each other; the trailing one is held until the
    # leading one has gone. A response channel has no peer, so its delay stays
    # a plain countdown of backpressure.
    lead = {"aw_delay": "w_delay", "w_delay": "aw_delay"}

    for field, chan in chans.items():
        cycles = getattr(profile, field)
        if not cycles:
            chan.clear_pause_generator()
            chan.pause = False
            continue
        if field in lead:
            # Pause now, synchronously: the write may be issued in this same
            # delta, before any task the backend starts could run.
            chan.clear_pause_generator()
            chan.pause = True
            _OCAH_RELEASERS[chan] = cocotb.start_soon(
                _release_on_leader_valid(chan, chans[lead[field]], cycles)
            )
        else:
            chan.set_pause_generator(_hold_then_go(cycles))


def clear_profile(driver) -> None:
    """Return every channel to the backend default (no pause)."""
    apply_profile(driver, AxiTimingProfile())


def _selftest() -> None:
    # A response channel has no peer to order against: the countdown starts
    # at once.
    g_resp = _hold_then_go(2)
    assert [next(g_resp) for _ in range(4)] == [True, True, False, False]


_selftest()
