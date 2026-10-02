# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold reset that lands while a register access is outstanding.

``doc/integrator/src/smu-sep.adoc`` (Clock and Reset Requirements) gives
``rst_ni`` asynchronous assertion, so the platform can assert it on any cycle,
including one where the CPU-LSU port has an access in flight. The software
resets cannot do that: each ``SW_RESET_N`` sequencer isolates and drains its
paths before its reset asserts (``hw/sys/sep/doc/reset_controller.adoc``,
Isolation and Reset Sequencing). This driver therefore uses ``rst_ni`` only.

One probe register per converted register port. Each probe is a software
read-write register whose reset value the register export states, so a read
after the reset grades the reset against the RDL, and a write/readback after
it grades the path against a value the test chose. The probe access goes out
on the VIP master directly with its own AXI ID, and ``SepResetLandWatch``
records the request and response handshakes on the ``s_axi`` pins: that record
is what places the reset inside the window between the last request handshake
and the response.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from sep_reg_meta import AES, CSRNG, EDN, HMAC, KMAC, OTBN, SPI_CONTROLLER, WDT_TIMER, RegBlock, sym

from seq_lib.sep_abr_keygen_seq import ABR_INTR
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# s_axi carries a 3-bit ID (tb/sep_tb_signal_list.svh). The sequencer issues
# ID 0, so a response with this ID after a reset can only belong to the
# abandoned probe access.
PROBE_ID = 3

# Bound on one probe access, in system clocks: the 50 us AXI timeout of
# sep_env_cfg at the 1.25 ns core period. The failure this bounds is a wedge.
PROBE_TIMEOUT_CYCLES = 40_000

# Reset offsets per (probe, op). A window of at most DENSE_LIMIT cycles is
# walked on every cycle; a longer one is sampled at SPREAD_POINTS evenly spaced
# cycles, both ends included.
DENSE_LIMIT = 24
SPREAD_POINTS = 10

_ABR_RDL = (
    Path(__file__).resolve().parents[6]
    / "vendor"
    / "chipsalliance"
    / "adams-bridge"
    / "upstream"
    / "src"
    / "abr_top"
    / "rtl"
    / "abr_reg.rdl"
)


def _abr_counter() -> tuple[int, int]:
    """Address and RDL reset of ``notif_cmd_done_intr_count_r``.

    ``abr_reg.rdl`` declares the counter as ``intr_count_t`` at ``@0x180``
    inside ``intr_block_rf``, with ``sw = rw`` and one 32-bit ``cnt`` field.
    """
    text = _ABR_RDL.read_text(encoding="utf-8")
    body = re.search(r"reg intr_count_t \{(?P<body>.*?)\n\s*\};", text, re.S)
    if body is None:
        raise RuntimeError(f"{_ABR_RDL} has no intr_count_t register type")
    cnt = re.search(r"\bcnt\[32\]\s*=\s*32'h([0-9A-Fa-f_]+)\s*;", body.group("body"))
    if cnt is None:
        raise RuntimeError(f"{_ABR_RDL} intr_count_t has no 32-bit cnt reset")
    off = re.search(r"intr_count_t\s+notif_cmd_done_intr_count_r\s*@\s*(0x[0-9A-Fa-f]+)", text)
    if off is None:
        raise RuntimeError(f"{_ABR_RDL} places no notif_cmd_done_intr_count_r")
    return ABR_INTR + int(off.group(1), 16), int(cnt.group(1).replace("_", ""), 16)


@dataclass(frozen=True)
class ResetProbe:
    """One read-write register behind one converted register port."""

    name: str
    addr: int
    reset: int
    mask: int
    shadowed: bool = False


def _reg(label: str, block: RegBlock, reg: str, *, shadowed: bool = False) -> ResetProbe:
    return ResetProbe(label, block.addr(reg), block.reset32(reg), block.mask32(reg), shadowed)


def _ot(label: str, block, reg: str) -> ResetProbe:
    return ResetProbe(
        label,
        sym(f"{block.block}_{reg}_REG_ADDR"),
        block.reset(reg) & 0xFFFF_FFFF,
        block.mask(reg) & 0xFFFF_FFFF,
    )


_ABR_COUNT_ADDR, _ABR_COUNT_RESET = _abr_counter()

# One probe per converted register port reachable from the CPU-LSU master.
# AES has no plain read-write register outside key material and its control
# registers, so its probe is the shadowed auxiliary control register.
PROBES: tuple[ResetProbe, ...] = (
    _reg("otbn", OTBN, "LOAD_CHECKSUM"),
    _reg("aes", AES, "CTRL_AUX_SHADOWED", shadowed=True),
    _reg("hmac", HMAC, "INTR_ENABLE"),
    _reg("kmac", KMAC, "ENTROPY_PERIOD"),
    _ot("csrng", CSRNG, "INTR_ENABLE"),
    _ot("edn", EDN, "INTR_ENABLE"),
    _reg("wdt", WDT_TIMER, "WKUP_THOLD_LO"),
    _reg("spi", SPI_CONTROLLER, "CONFIGOPTS"),
    _reg("dma", RegBlock("SECURE_DMA"), "SRC_ADDR_LO"),
    ResetProbe("abr", _ABR_COUNT_ADDR, _ABR_COUNT_RESET, 0xFFFF_FFFF),
)


def other_value(rng, mask: int, avoid: tuple[int, ...]) -> int:
    """Seed-derived value inside ``mask`` that differs from every value in ``avoid``."""
    for _ in range(64):
        v = rng.getrandbits(32) & mask
        if all(v != (a & mask) for a in avoid):
            return v
    raise RuntimeError(f"no value inside mask 0x{mask:08x} avoids {[hex(a) for a in avoid]}")


def reset_offsets(window: int) -> list[int]:
    """Cycles after the last request handshake at which the reset asserts."""
    if window <= 0:
        raise ValueError(f"response window {window} leaves no cycle to land a reset in")
    if window <= DENSE_LIMIT:
        return list(range(window))
    last = window - 1
    return sorted({round(i * last / (SPREAD_POINTS - 1)) for i in range(SPREAD_POINTS)})


def _hi(sig) -> bool:
    return str(sig.value) == "1"


def _id(sig) -> int | None:
    v = sig.value
    if not v.is_resolvable:
        return None
    return int(v)


@dataclass
class SepResetLandWatch:
    """Handshake record of one probe access on the ``s_axi`` pins.

    Cycle numbers count rising clock edges from the issue of the access.
    ``anchor`` is the edge on which the last request handshake completed (AR for
    a read; the later of AW and W for a write), ``resp`` the edge on which the
    probe ID's R or B beat was accepted.
    """

    op: str
    anchor: int | None = None
    resp: int | None = None
    resp_code: int | None = None
    aw_at: int | None = None
    w_at: int | None = None
    stale: list[tuple[str, int]] = field(default_factory=list)

    def sample(self, cycle: int) -> None:
        top = cocotb.top
        if self.op == "read":
            if (
                _hi(top.s_axi_arvalid)
                and _hi(top.s_axi_arready)
                and _id(top.s_axi_arid) == PROBE_ID
            ):
                if self.anchor is None:
                    self.anchor = cycle
            if _hi(top.s_axi_rvalid) and _hi(top.s_axi_rready) and _id(top.s_axi_rid) == PROBE_ID:
                if self.resp is None:
                    self.resp = cycle
                    self.resp_code = _id(top.s_axi_rresp)
        else:
            if (
                _hi(top.s_axi_awvalid)
                and _hi(top.s_axi_awready)
                and _id(top.s_axi_awid) == PROBE_ID
            ):
                if self.aw_at is None:
                    self.aw_at = cycle
            if _hi(top.s_axi_wvalid) and _hi(top.s_axi_wready) and self.w_at is None:
                self.w_at = cycle
            if self.anchor is None and self.aw_at is not None and self.w_at is not None:
                self.anchor = max(self.aw_at, self.w_at)
            if _hi(top.s_axi_bvalid) and _hi(top.s_axi_bready) and _id(top.s_axi_bid) == PROBE_ID:
                if self.resp is None:
                    self.resp = cycle
                    self.resp_code = _id(top.s_axi_bresp)


async def watch_stale(stop: list[bool], hits: list[tuple[str, float]]) -> None:
    """Record every R or B beat that carries ``PROBE_ID`` until ``stop[0]``.

    Started once the reset has asserted: the probe access was abandoned by the
    master, so a beat with its ID afterwards is a response the DUT kept across
    the reset.
    """
    top = cocotb.top
    cycle = 0
    while not stop[0]:
        await RisingEdge(top.clk_i)
        await ReadOnly()
        cycle += 1
        if _hi(top.s_axi_rvalid) and _hi(top.s_axi_rready) and _id(top.s_axi_rid) == PROBE_ID:
            hits.append(("R", cycle))
        if _hi(top.s_axi_bvalid) and _hi(top.s_axi_bready) and _id(top.s_axi_bid) == PROBE_ID:
            hits.append(("B", cycle))


class SepResetProbeDriver(SepAxiRegDriver):
    """Probe register access: sequencer reads/writes and the timed probe access."""

    _DRIVER_TAG = "RSTPROBE"

    async def write(self, probe: ResetProbe, value: int) -> None:
        """Write a probe register; a shadowed register takes the same value twice."""
        await self._wr(probe.addr, value)
        if probe.shadowed:
            await self._wr(probe.addr, value)

    async def commit(self, probe: ResetProbe, value: int) -> None:
        """Second write of a shadowed register after a single-beat probe write."""
        if probe.shadowed:
            await self._wr(probe.addr, value)

    async def read(self, probe: ResetProbe) -> int:
        return (await self._rd(probe.addr)) & probe.mask

    def issue(self, probe: ResetProbe, op: str, value: int):
        """Start the probe access on the VIP master and return its completion event."""
        axi = self.test.env.axi_agent.driver.axi
        if op == "read":
            return axi.init_read(address=probe.addr, length=4, size=2, arid=PROBE_ID)
        return axi.init_write(
            address=probe.addr, data=value.to_bytes(4, "little"), size=2, awid=PROBE_ID
        )

    async def run_probe(self, probe: ResetProbe, op: str, value: int, *, land_at: int | None):
        """Issue one probe access and follow it on the pins.

        With ``land_at`` None the access runs to its response. Otherwise the
        call returns on the falling clock edge ``land_at`` cycles after the
        anchor edge, with the response not yet accepted unless the watch says
        so; the caller asserts ``rst_ni`` there.
        """
        top = cocotb.top
        watch = SepResetLandWatch(op)
        ev = self.issue(probe, op, value)
        for cycle in range(1, PROBE_TIMEOUT_CYCLES + 1):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            watch.sample(cycle)
            if watch.resp is not None:
                break
            if land_at is not None and watch.anchor is not None and cycle - watch.anchor >= land_at:
                break
        else:
            raise AssertionError(
                f"{probe.name} {op} probe @0x{probe.addr:08x}: no "
                f"{'response' if land_at is None else 'request handshake'} within "
                f"{PROBE_TIMEOUT_CYCLES} cycles (anchor={watch.anchor} resp={watch.resp})"
            )
        await FallingEdge(top.clk_i)
        return ev, watch
