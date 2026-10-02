# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite stimulus and monitoring for one converter slave port.

``AxilPort`` drives the port through the cocotbext-axi channel endpoints that
``AxiLiteMaster`` is built from, so a test can issue any WSTRB value (the
master only produces contiguous strobes), queue requests back to back, and
throttle each channel's VALID or READY with a pause generator.

``AxilRawPort`` leaves every signal to the test, for scenarios that need a pin
held in one exact cycle.

``AxilMonitor`` watches the port passively whichever driver is attached. It
records every accepted request and its response, and checks the AXI rules the
converter owes its master: a response stays valid and unchanged until it is
taken, AW and W are accepted together, and a request is accepted only once the
previous response has been taken, with the AHB side idle while a response is
pending.
"""

from __future__ import annotations

import itertools
import logging
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import cocotb
from cocotb.triggers import Event, RisingEdge
from cocotbext.axi import AxiLiteBus
from cocotbext.axi.axil_channels import (
    AxiLiteARSource,
    AxiLiteARTransaction,
    AxiLiteAWSource,
    AxiLiteAWTransaction,
    AxiLiteBSink,
    AxiLiteRSink,
    AxiLiteWSource,
    AxiLiteWTransaction,
)

from .ahb_lite_slave import HTRANS_IDLE, sample

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

AXIL_INPUTS = (
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
)


def pause_pattern(rng, low_prob: float, max_run: int) -> Iterator[bool]:
    """Endless pause pattern: runs of 1..max_run paused cycles with probability low_prob."""
    while True:
        if rng.random() < low_prob:
            yield from itertools.repeat(True, rng.randint(1, max_run))
        else:
            yield False


@dataclass
class PortOp:
    """One request issued through ``AxilPort``."""

    kind: str
    addr: int
    prot: int
    data: int | None = None
    strb: int | None = None
    resp: int | None = None
    rdata: int | None = None
    flushed: bool = False

    def __post_init__(self) -> None:
        self.done = Event()


class AxilPort:
    """AXI4-Lite master on the ``<prefix>_*`` pins with arbitrary WSTRB."""

    def __init__(self, dut, prefix: str, clock, reset_n) -> None:
        bus = AxiLiteBus.from_prefix(dut, prefix)
        self.aw = AxiLiteAWSource(bus.write.aw, clock, reset_n, reset_active_level=False)
        self.w = AxiLiteWSource(bus.write.w, clock, reset_n, reset_active_level=False)
        self.b = AxiLiteBSink(bus.write.b, clock, reset_n, reset_active_level=False)
        self.ar = AxiLiteARSource(bus.read.ar, clock, reset_n, reset_active_level=False)
        self.r = AxiLiteRSink(bus.read.r, clock, reset_n, reset_active_level=False)
        self.log = logging.getLogger(f"cocotb.{prefix}")
        self.violations: list[str] = []
        self._pending_w: deque[PortOp] = deque()
        self._pending_r: deque[PortOp] = deque()
        cocotb.start_soon(self._b_loop())
        cocotb.start_soon(self._r_loop())

    def issue_write(self, addr: int, data: int, strb: int, prot: int = 0) -> PortOp:
        op = PortOp("W", addr, prot, data=data, strb=strb)
        self.aw.send_nowait(AxiLiteAWTransaction(awaddr=addr, awprot=prot))
        self.w.send_nowait(AxiLiteWTransaction(wdata=data, wstrb=strb))
        self._pending_w.append(op)
        return op

    def issue_read(self, addr: int, prot: int = 0) -> PortOp:
        op = PortOp("R", addr, prot)
        self.ar.send_nowait(AxiLiteARTransaction(araddr=addr, arprot=prot))
        self._pending_r.append(op)
        return op

    async def write(self, addr: int, data: int, strb: int = 0xF, prot: int = 0) -> int | None:
        op = self.issue_write(addr, data, strb, prot)
        await op.done.wait()
        return op.resp

    async def read(self, addr: int, prot: int = 0) -> tuple[int | None, int | None]:
        op = self.issue_read(addr, prot)
        await op.done.wait()
        return op.rdata, op.resp

    @property
    def outstanding(self) -> int:
        return len(self._pending_w) + len(self._pending_r)

    def set_valid_pause(self, aw=None, w=None, ar=None) -> None:
        self.aw.set_pause_generator(aw)
        self.w.set_pause_generator(w)
        self.ar.set_pause_generator(ar)

    def set_ready_pause(self, b=None, r=None) -> None:
        self.b.set_pause_generator(b)
        self.r.set_pause_generator(r)

    def flush(self) -> list[PortOp]:
        """Drop every pending request, as a reset does, and return them."""
        dropped = [*self._pending_w, *self._pending_r]
        for op in dropped:
            op.flushed = True
            op.done.set()
        self._pending_w.clear()
        self._pending_r.clear()
        return dropped

    async def _b_loop(self) -> None:
        while True:
            b = await self.b.recv()
            if not self._pending_w:
                self.violations.append(f"B response {b} with no write pending")
                continue
            op = self._pending_w.popleft()
            op.resp = int(b.bresp)
            op.done.set()

    async def _r_loop(self) -> None:
        while True:
            r = await self.r.recv()
            if not self._pending_r:
                self.violations.append(f"R response {r} with no read pending")
                continue
            op = self._pending_r.popleft()
            op.rdata = int(r.rdata)
            op.resp = int(r.rresp)
            op.done.set()


class AxilRawPort:
    """Direct pin access to the ``<prefix>_*`` inputs, all driven low at construction."""

    def __init__(self, dut, prefix: str) -> None:
        self._dut = dut
        self._prefix = prefix
        for name in AXIL_INPUTS:
            self.pin(name).value = 0

    def pin(self, name: str):
        return getattr(self._dut, f"{self._prefix}_{name}")

    def drive(self, **values: int) -> None:
        for name, value in values.items():
            self.pin(name).value = value

    def get(self, name: str) -> int | None:
        return sample(self.pin(name))


@dataclass
class AxilObservation:
    """A request the converter accepted, and the response it returned."""

    kind: str
    index: int
    addr: int
    prot: int
    accept_cycle: int
    data: int | None = None
    strb: int | None = None
    resp: int | None = None
    rdata: int | None = None
    resp_cycle: int | None = None


class AxilMonitor:
    """Passive checker on one converter's AXI4-Lite port and its AHB HTRANS."""

    def __init__(
        self, dut, axil_prefix: str, ahb_prefix: str, clock, reset_n, name: str | None = None
    ) -> None:
        self.name = name or axil_prefix
        self.log = logging.getLogger(f"cocotb.{self.name}")
        self._clock = clock
        self._reset_n = reset_n
        self._sig = {
            s: getattr(dut, f"{axil_prefix}_{s}")
            for s in (
                "awaddr",
                "awprot",
                "awvalid",
                "awready",
                "wdata",
                "wstrb",
                "wvalid",
                "wready",
                "bresp",
                "bvalid",
                "bready",
                "araddr",
                "arprot",
                "arvalid",
                "arready",
                "rdata",
                "rresp",
                "rvalid",
                "rready",
            )
        }
        self._htrans = getattr(dut, f"{ahb_prefix}_htrans")

        self.observations: list[AxilObservation] = []
        self.violations: list[str] = []
        self.on_accept: list[Callable[[AxilObservation], None]] = []
        self.on_response: list[Callable[[AxilObservation], None]] = []
        self.on_reset: list[Callable[[], None]] = []

        self.cycle = 0
        self.r_stall_edges = 0
        self.b_stall_edges = 0
        self.max_r_stall_run = 0
        self.max_b_stall_run = 0
        self.ar_wait_edges = 0

        self._outstanding: AxilObservation | None = None
        self._r_hold: tuple[int | None, int | None] | None = None
        self._b_hold: int | None = None
        self._r_run = 0
        self._b_run = 0
        self._in_reset = True
        cocotb.start_soon(self._run())

    @property
    def outstanding(self) -> AxilObservation | None:
        return self._outstanding

    def _violation(self, msg: str) -> None:
        text = f"[{self.name} cycle {self.cycle}] {msg}"
        self.violations.append(text)
        self.log.error("AXI violation: %s", text)

    async def _run(self) -> None:
        edge = RisingEdge(self._clock)
        while True:
            await edge
            self.cycle += 1
            if sample(self._reset_n) != 1:
                if not self._in_reset:
                    self._in_reset = True
                    for cb in self.on_reset:
                        cb()
                self._outstanding = None
                self._r_hold = self._b_hold = None
                self._r_run = self._b_run = 0
                continue
            self._in_reset = False
            self._step()

    def _step(self) -> None:
        v = {name: sample(sig) for name, sig in self._sig.items()}
        htrans = sample(self._htrans)
        for name in ("awready", "wready", "bvalid", "arready", "rvalid"):
            if v[name] is None:
                self._violation(f"{name} is X/Z outside reset")
                v[name] = 0

        # A response stays valid, with its payload unchanged, until it is taken.
        if self._r_hold is not None and (
            not v["rvalid"] or (v["rdata"], v["rresp"]) != self._r_hold
        ):
            self._violation(
                f"R changed before RREADY: {self._r_hold} -> "
                f"valid={v['rvalid']} {(v['rdata'], v['rresp'])}"
            )
        if self._b_hold is not None and (not v["bvalid"] or v["bresp"] != self._b_hold):
            self._violation(
                f"B changed before BREADY: {self._b_hold} -> valid={v['bvalid']} {v['bresp']}"
            )
        r_stall = bool(v["rvalid"]) and not v["rready"]
        b_stall = bool(v["bvalid"]) and not v["bready"]
        self._r_hold = (v["rdata"], v["rresp"]) if r_stall else None
        self._b_hold = v["bresp"] if b_stall else None
        self._r_run = self._r_run + 1 if r_stall else 0
        self._b_run = self._b_run + 1 if b_stall else 0
        self.r_stall_edges += r_stall
        self.b_stall_edges += b_stall
        self.max_r_stall_run = max(self.max_r_stall_run, self._r_run)
        self.max_b_stall_run = max(self.max_b_stall_run, self._b_run)

        if v["rvalid"] and v["bvalid"]:
            self._violation("R and B valid together")
        if (v["rvalid"] or v["bvalid"]) and htrans != HTRANS_IDLE:
            self._violation(f"HTRANS={htrans} while an AXI response is pending")
        if v["awready"] != v["wready"]:
            self._violation(f"AWREADY={v['awready']} and WREADY={v['wready']} differ")

        self.ar_wait_edges += bool(v["arvalid"]) and not v["arready"]

        # Responses first: a request accepted on the same edge must still find
        # the previous one closed.
        if v["rvalid"] and v["rready"]:
            self._respond("R", rdata=v["rdata"], resp=v["rresp"])
        if v["bvalid"] and v["bready"]:
            self._respond("W", resp=v["bresp"])

        ar_hs = bool(v["arvalid"]) and bool(v["arready"])
        aw_hs = bool(v["awvalid"]) and bool(v["awready"])
        w_hs = bool(v["wvalid"]) and bool(v["wready"])
        if aw_hs != w_hs:
            self._violation(f"AW handshake={aw_hs} and W handshake={w_hs} on the same edge")
        if ar_hs and aw_hs:
            self._violation("read and write accepted on the same edge")
        if ar_hs:
            addr, prot = self._request_fields(v, "araddr", "arprot")
            self._accept(AxilObservation("R", len(self.observations), addr, prot, self.cycle))
        elif aw_hs and w_hs:
            addr, prot = self._request_fields(v, "awaddr", "awprot")
            self._accept(
                AxilObservation(
                    "W",
                    len(self.observations),
                    addr,
                    prot,
                    self.cycle,
                    data=v["wdata"],
                    strb=v["wstrb"],
                )
            )

    def _request_fields(
        self, v: dict[str, int | None], addr_name: str, prot_name: str
    ) -> tuple[int, int]:
        """Address and protection of an accepted request; X/Z is a violation and reads as 0."""
        addr, prot = v[addr_name], v[prot_name]
        if addr is None or prot is None:
            self._violation(f"{addr_name}={addr} {prot_name}={prot} X/Z on an accepted request")
        return addr or 0, prot or 0

    def _accept(self, obs: AxilObservation) -> None:
        if self._outstanding is not None:
            self._violation(
                f"{obs.kind} accepted while {self._outstanding.kind} "
                f"#{self._outstanding.index} awaits its response"
            )
        self._outstanding = obs
        self.observations.append(obs)
        for cb in self.on_accept:
            cb(obs)

    def _respond(self, kind: str, resp: int | None, rdata: int | None = None) -> None:
        obs = self._outstanding
        if obs is None or obs.kind != kind:
            self._violation(f"{kind} response with no matching request outstanding ({obs})")
            return
        obs.resp = resp
        obs.rdata = rdata
        obs.resp_cycle = self.cycle
        self._outstanding = None
        for cb in self.on_response:
            cb(obs)
