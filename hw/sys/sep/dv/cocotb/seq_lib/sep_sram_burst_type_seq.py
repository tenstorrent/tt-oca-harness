# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FIXED and WRAP bursts into SEP SRAM, for sep_sram_burst_type_test.

``hw/sys/sep/doc/fabric.adoc`` specifies the SEP interconnect as an AXI4
fabric. AXI4 gives each burst type its own beat addresses: a FIXED burst
repeats its start address on every beat, and a WRAP burst increments within
an aligned window of ``beats * beat_bytes`` bytes and wraps to its start.
The golden below is that address rule and nothing else.

A slave that answers OKAY must have performed the burst the ``AxBURST``
field names. A slave may also refuse a burst type it does not implement;
then the response is an error and SRAM keeps its background. Any other
outcome -- OKAY with INCR beat addresses in particular -- is the failure
this sequence exists to find.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import sym

from seq_lib.sep_axi_access_seq import (
    SepAxiAccessSeq,
    capture_addr_handshake,
    take_handshake,
)

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")

BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2
RESP_OKAY = 0
RESP_DECERR = 3

BEATS = 4
BEAT_BYTES = 8  # full bus width, AxSIZE = 3
SIZE = 3
_MASK64 = 0xFFFF_FFFF_FFFF_FFFF


def beat_addrs(burst: int, start: int, beats: int = BEATS, nbytes: int = BEAT_BYTES) -> list[int]:
    """AXI4 beat addresses for an aligned burst of ``beats`` x ``nbytes``."""
    if burst == BURST_FIXED:
        return [start] * beats
    if burst == BURST_INCR:
        return [start + i * nbytes for i in range(beats)]
    if burst == BURST_WRAP:
        span = beats * nbytes
        lo = start & ~(span - 1)
        return [lo + ((start - lo + i * nbytes) % span) for i in range(beats)]
    raise ValueError(f"unknown burst type {burst}")


@dataclass(frozen=True)
class BurstCase:
    name: str
    burst: int
    start: int
    # Words the check reads back: the burst's own window plus one word on
    # each side that an INCR walk would reach and the named burst must not.
    region: tuple[int, ...]


def burst_cases() -> tuple[BurstCase, ...]:
    fixed = SEP_SRAM_BASE + 0x6000
    wrap_lo = SEP_SRAM_BASE + 0x6100  # WRAP window base, aligned to BEATS * BEAT_BYTES
    wrap_start = wrap_lo + 2 * BEAT_BYTES
    span = BEATS * BEAT_BYTES
    return (
        BurstCase(
            "FIXED",
            BURST_FIXED,
            fixed,
            tuple(fixed + i * BEAT_BYTES for i in range(-1, BEATS + 1)),
        ),
        BurstCase(
            "WRAP",
            BURST_WRAP,
            wrap_start,
            tuple(wrap_lo + i * BEAT_BYTES for i in range(-1, span // BEAT_BYTES + 2)),
        ),
    )


def background(addr: int) -> int:
    return (0x5EED_0000_0000_0000 | addr) & _MASK64


def burst_word(case: BurstCase, beat: int) -> int:
    return (0xB000_0000_0000_0000 | (case.burst << 40) | (beat << 32) | case.start) & _MASK64


def golden_after_write(case: BurstCase) -> dict[int, int]:
    """SRAM image after an OKAY write burst of this type under AXI4."""
    img = {a: background(a) for a in case.region}
    for i, a in enumerate(beat_addrs(case.burst, case.start)):
        img[a] = burst_word(case, i)
    return img


def golden_read(case: BurstCase, img: dict[int, int]) -> list[int]:
    """Beats an OKAY read burst of this type returns under AXI4."""
    return [img[a] for a in beat_addrs(case.burst, case.start)]


class SepSramBurstType:
    """Background fill, one burst, then single-beat readback of the region."""

    def __init__(self, test) -> None:
        self.test = test

    async def _single(self, op: SepAxiOp, addr: int, wdata: int = 0) -> int:
        seq = SepAxiAccessSeq(
            f"bt_{op.value}_0x{addr:08x}", op=op, addr=addr, wdata=wdata, length=8
        )
        await self.test.start_seq(seq)
        assert not seq.timed_out and seq.resp_code == RESP_OKAY, (
            f"single-beat {op.value} 0x{addr:08x} resp={seq.resp_code} "
            f"timed_out={seq.timed_out}; the SRAM control path is not live"
        )
        return seq.rdata & _MASK64

    async def fill(self, case: BurstCase) -> None:
        for a in case.region:
            await self._single(SepAxiOp.WRITE, a, background(a))

    async def image(self, case: BurstCase) -> dict[int, int]:
        return {a: await self._single(SepAxiOp.READ, a) for a in case.region}

    async def write_burst(self, case: BurstCase) -> tuple[int, bool, dict | None]:
        data = b"".join(burst_word(case, i).to_bytes(BEAT_BYTES, "little") for i in range(BEATS))
        mon = self.test.env.axi_monitor
        mon.arm_expected_decerr(1)
        aw = cocotb.start_soon(capture_addr_handshake("aw"))
        seq = SepAxiAccessSeq(
            f"bt_wr_{case.name}_0x{case.start:08x}",
            op=SepAxiOp.WRITE,
            addr=case.start,
            wdata=int.from_bytes(data, "little"),
            length=len(data),
            size=SIZE,
            burst=case.burst,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        if seq.timed_out or seq.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)
        return seq.resp_code, seq.timed_out, take_handshake(aw)

    async def read_burst(self, case: BurstCase) -> tuple[list[int], list[int], bool, dict | None]:
        """Beat data and the per-beat RRESP vector the monitor captured."""
        mon = self.test.env.axi_monitor
        mon.start_beat_capture()
        mon.arm_expected_decerr(BEATS)
        ar = cocotb.start_soon(capture_addr_handshake("ar"))
        seq = SepAxiAccessSeq(
            f"bt_rd_{case.name}_0x{case.start:08x}",
            op=SepAxiOp.READ,
            addr=case.start,
            length=BEATS * BEAT_BYTES,
            size=SIZE,
            burst=case.burst,
            allow_ungraded_read_resp=True,
        )
        await self.test.start_seq(seq)
        captured = mon.take_beat_capture()
        resps = [r for r in captured if r is not None] if len(captured) == BEATS else []
        used = sum(1 for r in resps if r == RESP_DECERR)
        if BEATS > used:
            mon.release_expected_decerr(BEATS - used)
        words = [(seq.rdata >> (64 * i)) & _MASK64 for i in range(BEATS)]
        return words, resps, seq.timed_out, take_handshake(ar)


def stim_miss(case: BurstCase, hs: dict | None) -> str | None:
    """None when the master presented this case's burst on the pins."""
    want = {"addr": case.start, "len": BEATS - 1, "size": SIZE, "burst": case.burst}
    if hs is None:
        return "no address handshake seen on the port"
    if hs != want:
        return f"pins carried {hs}, expected {want}"
    return None


def _selftest() -> None:
    fixed, wrap = burst_cases()
    assert beat_addrs(BURST_FIXED, fixed.start) == [fixed.start] * BEATS
    lo = wrap.start & ~(BEATS * BEAT_BYTES - 1)
    assert beat_addrs(BURST_WRAP, wrap.start) == [lo + 16, lo + 24, lo, lo + 8]
    for case in (fixed, wrap):
        # The named burst and an INCR walk from the same start must leave
        # different images, or the check could not tell them apart.
        incr = {a: background(a) for a in case.region}
        for i, a in enumerate(beat_addrs(BURST_INCR, case.start)):
            incr[a] = burst_word(case, i)
        assert incr != golden_after_write(case), f"{case.name} golden equals INCR"
        assert set(beat_addrs(case.burst, case.start)) <= set(case.region)
        assert set(beat_addrs(BURST_INCR, case.start)) <= set(case.region)


_selftest()
