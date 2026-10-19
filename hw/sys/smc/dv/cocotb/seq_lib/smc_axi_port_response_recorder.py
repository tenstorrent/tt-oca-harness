# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive recorders: B and R handshakes of an inbound port, AW and AR handshakes of SYS_OUT.

The VIP response-ID capture is scoped to one blocking transaction, so responses of
outstanding accesses are attributed here, per port, from the flat signals of the bench.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_axi_port_watch import SmcAxiPortWatch


def _sample(dut, name: str) -> int:
    sig = getattr(dut, name)
    assert sig.value.is_resolvable, f"{name} is X/Z ({sig.value})"
    return int(sig.value)


def _sample_or_none(dut, name: str) -> int | None:
    value = getattr(dut, name).value
    return int(value) if value.is_resolvable else None


@dataclass(frozen=True)
class PortResponse:
    """One accepted B beat (``chan`` "b") or R beat (``chan`` "r") of a port.

    ``data`` is None on an R beat whose RDATA is unresolvable; a read that is
    only observed may return X and the consumer decides whether that matters.
    """

    chan: str
    ident: int
    resp: int
    data: int | None
    last: int
    time_ps: int


class SmcAxiPortResponseRecorder:
    """Log every B and R handshake of one flat AXI port per clk_smc_i edge."""

    def __init__(self, dut, prefix: str) -> None:
        self.dut = dut
        self.prefix = prefix
        self.stop = False
        self.events: list[PortResponse] = []

    def mark(self) -> int:
        return len(self.events)

    def since(self, mark: int) -> list[PortResponse]:
        return self.events[mark:]

    async def run(self) -> None:
        dut, p = self.dut, self.prefix
        while not self.stop:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            now = int(get_sim_time("ps"))
            if _sample(dut, f"{p}_bvalid") and _sample(dut, f"{p}_bready"):
                self.events.append(
                    PortResponse(
                        "b",
                        _sample(dut, f"{p}_bid"),
                        _sample(dut, f"{p}_bresp"),
                        0,
                        1,
                        now,
                    )
                )
            if _sample(dut, f"{p}_rvalid") and _sample(dut, f"{p}_rready"):
                self.events.append(
                    PortResponse(
                        "r",
                        _sample(dut, f"{p}_rid"),
                        _sample(dut, f"{p}_rresp"),
                        _sample_or_none(dut, f"{p}_rdata"),
                        _sample(dut, f"{p}_rlast"),
                        now,
                    )
                )


@dataclass(frozen=True)
class OutputHandshake:
    """One accepted AW (``chan`` "aw") or AR (``chan`` "ar") beat on u_output_axi_if.

    ``cycle`` is the sampler's clk_smc_i edge count at the handshake.
    """

    chan: str
    addr: int
    cache: int
    user: int
    ident: int
    length: int
    cycle: int


@dataclass(frozen=True)
class OutputResponse:
    """One accepted B beat (``chan`` "b") or RLAST beat (``chan`` "r") on u_output_axi_if."""

    chan: str
    ident: int
    cycle: int


class SmcOutputHandshakeSampler:
    """Log the AW, AR, B and RLAST handshakes of u_output_axi_if per clk_smc_i edge.

    ``stalls`` counts the edges on which AW or AR was valid with READY low.
    """

    def __init__(self) -> None:
        self.stop = False
        self.events: list[OutputHandshake] = []
        self.resps: list[OutputResponse] = []
        self.stalls = {"aw": 0, "ar": 0}
        self.cycle = 0

    def mark(self) -> int:
        return len(self.events)

    def since(self, mark: int, chan: str | None = None) -> list[OutputHandshake]:
        return [e for e in self.events[mark:] if chan is None or e.chan == chan]

    def mark_resps(self) -> int:
        return len(self.resps)

    def resps_since(self, mark: int) -> list[OutputResponse]:
        return self.resps[mark:]

    @staticmethod
    def _handshake(ifc, ch: str) -> bool | None:
        """True on a handshake, False when idle, None when valid without ready."""
        valid, ready = (getattr(ifc, f"{ch}{n}") for n in ("valid", "ready"))
        assert valid.value.is_resolvable and ready.value.is_resolvable, (
            f"u_output_axi_if {ch}valid/{ch}ready are X/Z"
        )
        if not int(valid.value):
            return False
        return True if int(ready.value) else None

    async def run(self) -> None:
        top: Any = cocotb.top
        ifc = top.u_output_axi_if
        while not self.stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            self.cycle += 1
            for ch in ("aw", "ar"):
                state = self._handshake(ifc, ch)
                if state is None:
                    self.stalls[ch] += 1
                if not state:
                    continue
                names = ("addr", "cache", "user", "id", "len")
                sigs = [getattr(ifc, f"{ch}{n}") for n in names]
                assert all(s.value.is_resolvable for s in sigs), (
                    f"u_output_axi_if {ch} payload is X/Z on a handshake"
                )
                addr, cache, user, ident, length = (int(s.value) for s in sigs)
                self.events.append(
                    OutputHandshake(ch, addr, cache, user, ident, length, self.cycle)
                )
            for ch in ("b", "r"):
                if not self._handshake(ifc, ch):
                    continue
                sigs = [getattr(ifc, f"{ch}id")] + ([ifc.rlast] if ch == "r" else [])
                assert all(s.value.is_resolvable for s in sigs), (
                    f"u_output_axi_if {ch}id/rlast is X/Z on a handshake"
                )
                if ch == "r" and not int(ifc.rlast.value):
                    continue
                self.resps.append(OutputResponse(ch, int(sigs[0].value), self.cycle))


class SmcRawRStallWatch(SmcAxiPortWatch):
    """SmcAxiPortWatch whose R stall is the raw R valid high without a handshake.

    On SEP_IN and SYS_IN the bench gates RVALID from the manager while it holds R, so
    VALID high with READY low never shows on the port; the raw valid probe does.
    """

    def __init__(self, dut, prefix: str, raw_r_valid: str | None = None) -> None:
        super().__init__(dut, prefix)
        self.raw_r_valid = raw_r_valid
        self.stalls["w"] = 0
        self.valid_cycles = {name: 0 for name in self.stalls}
        self.cycles = 0

    async def run(self) -> None:
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            self.cycles += 1
            for channel in self.stalls:
                valid, ready = self._read(f"{channel}valid"), self._read(f"{channel}ready")
                if valid == 1:
                    self.valid_cycles[channel] += 1
                if channel == "r" and self.raw_r_valid is not None:
                    sig = getattr(self.dut, self.raw_r_valid).value
                    raw = int(sig) if sig.is_resolvable else None
                    if raw == 1 and (valid, ready) != (1, 1):
                        self.stalls[channel] += 1
                elif valid == 1 and ready == 0:
                    self.stalls[channel] += 1
