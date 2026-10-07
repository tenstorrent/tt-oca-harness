# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: the responder holds a configured outstanding depth.

Wire-level proof on the t_axi bundle against an ``OcahAxiSlaveAgent`` built
with ``max_outstanding=DEPTH``. With BREADY or RREADY held low, the responder
accepts exactly DEPTH address phases and then holds AWREADY or ARREADY low,
so it neither stops short of the depth nor exceeds it; ``outstanding_peak``
reports the same DEPTH. The first request's response is then delayed while
every later one is not: responses of other IDs overtake it, responses of its
own ID wait behind it, and the reads return each request's own data, so the
per-ID order is judged from the data and not from the ID alone. The requests
held back by the full window are accepted once responses retire. Every
response on the wires is counted, in total and per ID, through a quiet window
longer than any response delay, so a missing or surplus response fails.
"""

from __future__ import annotations

import logging
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_axi_vip_harness import build_wire_slave, start_clock_reset
from ocah_checker import OcahChecker

log = logging.getLogger("cocotb.tb.ocah_axi_slave_outstanding_test")

CHK_DEPTH = "CHK-AXI-OUTSTANDING-DEPTH"
CHK_PEAK = "CHK-AXI-OUTSTANDING-PEAK"
CHK_ORDER = "CHK-AXI-OUTSTANDING-ID-ORDER"
CHK_OVERTAKE = "CHK-AXI-OUTSTANDING-OVERTAKE"
CHK_DATA = "CHK-AXI-OUTSTANDING-DATA"
CHK_COUNT = "CHK-AXI-OUTSTANDING-COUNT"

DEPTH = 8
# Two requests beyond the depth, so the full window is observable.
IDS = (1, 2, 1, 3, 2, 1, 3, 2, 4, 1)
DELAYED_ID = IDS[0]
HEAD_DELAY = 30
# Cycles the requests beyond the depth are offered with no response retiring.
FULL_WINDOW_CYCLES = 3 * HEAD_DELAY
DRAIN_CYCLES = 400
# Cycles watched after the last expected response, longer than any response
# delay, so a surplus response would land inside them.
QUIET_CYCLES = 2 * HEAD_DELAY
READ_BASE = 0x1000
WRITE_BASE = 0x2000


def _high(handle) -> bool:
    value = handle.value
    return value.is_resolvable and bool(int(value))


class _Wires:
    """Every handshake on the t_axi bundle, by cycle."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.cycle = 0
        self.aw: list[int] = []
        self.ar: list[int] = []
        self.b: list[tuple[int, int]] = []
        self.r: list[tuple[int, int, int]] = []
        cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk)
            self.cycle += 1
            if _high(dut.t_axi_awvalid) and _high(dut.t_axi_awready):
                self.aw.append(self.cycle)
            if _high(dut.t_axi_arvalid) and _high(dut.t_axi_arready):
                self.ar.append(self.cycle)
            if _high(dut.t_axi_bvalid) and _high(dut.t_axi_bready):
                self.b.append((self.cycle, int(dut.t_axi_bid.value)))
            if _high(dut.t_axi_rvalid) and _high(dut.t_axi_rready):
                self.r.append((self.cycle, int(dut.t_axi_rid.value), int(dut.t_axi_rdata.value)))


async def _offer(dut, channel: str, fields: list[dict[str, int]]) -> None:
    """Offer each beat on ``channel`` back to back, holding VALID until READY."""
    valid = getattr(dut, f"t_axi_{channel}valid")
    ready = getattr(dut, f"t_axi_{channel}ready")
    for beat in fields:
        for name, value in beat.items():
            getattr(dut, f"t_axi_{channel}{name}").value = value
        valid.value = 1
        while True:
            await RisingEdge(dut.clk)
            if _high(ready):
                break
    valid.value = 0


def _address_phase(request_id: int, addr: int) -> dict[str, int]:
    return {"id": request_id, "addr": addr, "len": 0, "size": 2, "burst": 1}


def _data(index: int) -> int:
    return 0xA5A5_0000 | index


def _check_window(checker, handshakes, responses, kind: str) -> None:
    """DEPTH requests accepted before the first response, none beyond it."""
    checker.expect_equal(
        CHK_DEPTH,
        (len(handshakes), len(responses)),
        (DEPTH, 0),
        context=f"{kind}: requests accepted and responses retired with the response READY low "
        f"for {FULL_WINDOW_CYCLES} cycles",
    )


async def _drain(dut, responses: list) -> None:
    """Wait for every expected response, then watch QUIET_CYCLES more."""
    for _ in range(DRAIN_CYCLES):
        await RisingEdge(dut.clk)
        if len(responses) >= len(IDS):
            break
    await ClockCycles(dut.clk, QUIET_CYCLES)


def _check_count(checker, ids: list[int], kind: str) -> None:
    """One response per request, per ID, and none beyond them."""
    checker.expect_equal(
        CHK_COUNT,
        (len(ids), sorted(Counter(ids).items())),
        (len(IDS), sorted(Counter(IDS).items())),
        context=f"{kind}: responses in total and per ID, through {QUIET_CYCLES} quiet cycles",
    )


def _check_order(checker, order: list[int], kind: str) -> None:
    """Same-ID responses in request order; a later ID overtakes the delayed request."""
    for request_id in sorted(set(IDS)):
        mine = [index for index in order if IDS[index] == request_id]
        checker.expect_equal(
            CHK_ORDER,
            mine,
            sorted(mine),
            context=f"{kind}: ID {request_id} responses in request order",
        )
    checker.expect_true(
        CHK_OVERTAKE,
        order[0] != 0,
        context=f"{kind}: a later request of another ID answered before delayed request 0, "
        f"order={order}",
    )


async def _reads(dut, slave, wires, checker) -> None:
    seq = slave.sequence
    for index in range(len(IDS)):
        seq.write32(READ_BASE + 4 * index, _data(index))
    dut.t_axi_rready.value = 0
    seq.set_response_delay([HEAD_DELAY], write=False)
    offer = cocotb.start_soon(
        _offer(
            dut,
            "ar",
            [_address_phase(rid, READ_BASE + 4 * i) for i, rid in enumerate(IDS)],
        )
    )
    await ClockCycles(dut.clk, FULL_WINDOW_CYCLES)
    _check_window(checker, list(wires.ar), list(wires.r), "read")
    dut.t_axi_rready.value = 1
    await _drain(dut, wires.r)
    await offer
    seq.clear_response_delay()
    log.info("read handshakes ar=%s r=%s", wires.ar, wires.r)
    _check_count(checker, [rid for _, rid, _ in wires.r], "read")
    checker.expect_equal(
        CHK_DATA,
        sorted((data, rid) for _, rid, data in wires.r),
        sorted((_data(i), rid) for i, rid in enumerate(IDS)),
        context="read: every request answered once with its own data and ID",
    )
    order = [data & 0xFFFF for _, _, data in wires.r]
    _check_order(checker, order, "read")


async def _writes(dut, slave, wires, checker) -> None:
    seq = slave.sequence
    dut.t_axi_bready.value = 0
    seq.set_response_delay([HEAD_DELAY], read=False)
    aw = cocotb.start_soon(
        _offer(
            dut,
            "aw",
            [_address_phase(wid, WRITE_BASE + 4 * i) for i, wid in enumerate(IDS)],
        )
    )
    w = cocotb.start_soon(
        _offer(dut, "w", [{"data": _data(i), "strb": 0xF, "last": 1} for i in range(len(IDS))])
    )
    await ClockCycles(dut.clk, FULL_WINDOW_CYCLES)
    _check_window(checker, list(wires.aw), list(wires.b), "write")
    dut.t_axi_bready.value = 1
    await _drain(dut, wires.b)
    await aw
    await w
    seq.clear_response_delay()
    log.info("write handshakes aw=%s b=%s", wires.aw, wires.b)
    bids = [bid for _, bid in wires.b]
    _check_count(checker, bids, "write")
    checker.expect_equal(
        CHK_DATA,
        (sorted(bids), [seq.read32(WRITE_BASE + 4 * i) for i in range(len(IDS))]),
        (sorted(IDS), [_data(i) for i in range(len(IDS))]),
        context="write: one B per request and every write held in memory",
    )
    # A B carries only its ID, so the order of the window's responses is
    # judged per ID: every B of the delayed ID waits behind request 0, and
    # the window's other IDs, issued later, answer first.
    window = bids[:DEPTH]
    first_delayed = window.index(DELAYED_ID)
    checker.expect_equal(
        CHK_ORDER,
        window[first_delayed:],
        [DELAYED_ID] * (DEPTH - first_delayed),
        context=f"write: no B of ID {DELAYED_ID} before delayed request 0, window={window}",
    )
    checker.expect_true(
        CHK_OVERTAKE,
        first_delayed > 0,
        context=f"write: B of later IDs answered before delayed request 0, window={window}",
    )


@cocotb.test()
async def ocah_axi_slave_outstanding_test(dut) -> None:
    await start_clock_reset(dut)
    slave = build_wire_slave(dut, max_outstanding=DEPTH)
    await ClockCycles(dut.clk, 2)
    checker = OcahChecker(
        name="ocah_axi_slave_outstanding_test",
        required_ids=(CHK_DEPTH, CHK_PEAK, CHK_ORDER, CHK_OVERTAKE, CHK_DATA, CHK_COUNT),
        logger=log,
    )
    checker.expect_equal(CHK_DEPTH, slave.sequence.max_outstanding, DEPTH, context="config")
    wires = _Wires(dut)
    await _reads(dut, slave, wires, checker)
    await _writes(dut, slave, wires, checker)
    _check_count(checker, [rid for _, rid, _ in wires.r], "read, after the write phase")
    checker.expect_equal(
        CHK_PEAK,
        slave.sequence.outstanding_peak(),
        {"write": DEPTH, "read": DEPTH},
        context="most transactions the responder reports outstanding at once",
    )
    checker.finalize()
