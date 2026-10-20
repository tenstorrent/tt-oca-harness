# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Responder controls and window counters for the outbound stall and saturation leaf.

The responder (``tb/sep_outbound_mbx.sv``) is steered only through its top
ports: ``smn_outbound_resp_hold_i`` keeps it from raising a new B or R VALID
(one already on offer completes) while requests are still accepted, and bit 0,
1 and 2 of ``smn_outbound_ready_stall_i`` keep AW, W and AR READY low. The
counters read the handshakes of the two TB masters (``PinWatch``) and of the
outbound port taps, attributing every PR-OUT request to its initiator by
address (``Layout``).

Contents:

* ``RespCtl``: drive of the hold and the READY stall mask, and the release of
  one response beat per channel.
* ``Meter``: the counts of one window at the master pins and at the port.
* ``altered_requests``: PR-OUT requests that differ from what was issued.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_fabric_common import SepSrcIdGrade

from seq_lib.sep_outbound_contention_seq import INITS, MIN_ID, Layout

CH_MASK = {"aw": 0b001, "w": 0b010, "ar": 0b100}


class RespCtl:
    """The responder hold and READY stall inputs of the bench."""

    def __init__(self) -> None:
        self.dut = cocotb.top

    def hold(self, on: bool) -> None:
        self.dut.smn_outbound_resp_hold_i.value = 1 if on else 0

    def stall(self, mask: int) -> None:
        self.dut.smn_outbound_ready_stall_i.value = mask

    def clear(self) -> None:
        self.hold(False)
        self.stall(0)

    async def release_after(self, cycles: int) -> None:
        """Clear both controls after ``cycles`` clocks."""
        await ClockCycles(self.dut.clk_i, cycles)
        self.clear()

    async def release_one(self, rsp_tap, *, bound_cycles: int = 8) -> int:
        """Lower the hold for one clock, so each response channel may raise one VALID.

        A VALID once raised stays up until its handshake, so at most one B and
        one R beat leave per call. Returns the beats seen at the response tap
        within ``bound_cycles`` of the pulse.
        """
        base = len(rsp_tap.beats)
        self.hold(False)
        await ClockCycles(self.dut.clk_i, 1)
        self.hold(True)
        await ClockCycles(self.dut.clk_i, bound_cycles)
        return len(rsp_tap.beats) - base


class Meter:
    """Counts since construction at the master pins and at the outbound port."""

    def __init__(self, bench) -> None:
        self.b = bench
        self.out0 = len(bench.out.beats)
        self.rsp0 = len(bench.rsp.beats)
        self.s0 = bench.pin_s.mark()
        self.m0 = bench.pin_m.mark()
        self.stall0 = {
            "lsu": (bench.pin_s.aw_stall, bench.pin_s.ar_stall),
            "sysif": (bench.pin_m.aw_stall, bench.pin_m.ar_stall),
        }

    def read(self) -> dict:
        b = self.b
        lay: Layout = b.layout
        res: dict = {"mst": {}, "port": {}}
        for init, pw, mark in (("lsu", b.pin_s, self.s0), ("sysif", b.pin_m, self.m0)):
            lo, hi = lay.span(init)
            floor = MIN_ID[pw.bus]

            def known(x, floor=floor):
                return all(v is not None for v in x[1:]) and x[1] >= floor

            aw = [x for x in pw.aw[mark[0] :] if known(x) and lo <= x[2] < hi]
            ar = [x for x in pw.ar[mark[2] :] if known(x) and lo <= x[2] < hi]
            res["mst"][init] = {
                "aw": len(aw),
                "ar": len(ar),
                "aw_stall": pw.aw_stall - self.stall0[init][0],
                "ar_stall": pw.ar_stall - self.stall0[init][1],
                "b": sum(1 for x in pw.b[mark[1] :] if known(x)),
                "r": sum(1 for x in pw.r[mark[3] :] if known(x)),
            }
        out = b.out.beats[self.out0 :]
        for init in INITS:
            res["port"][init] = {"aw": 0, "ar": 0}
        for beat in out:
            if beat.ch not in ("aw", "ar"):
                continue
            owner = lay.owner(beat.fields.get("addr"))
            if owner is not None:
                res["port"][owner][beat.ch] += 1
        res["port_aw"] = sum(res["port"][i]["aw"] for i in INITS)
        res["port_ar"] = sum(res["port"][i]["ar"] for i in INITS)
        rsp = b.rsp.beats[self.rsp0 :]
        res["port_b"] = sum(1 for x in rsp if x.ch == "b")
        res["port_r"] = sum(1 for x in rsp if x.ch == "r")
        res["mst_b"] = sum(v["b"] for v in res["mst"].values())
        res["mst_r"] = sum(v["r"] for v in res["mst"].values())
        return res

    @staticmethod
    def key(snap: dict) -> tuple:
        """The accepted counts of a snapshot, for the stops-rising comparison."""
        m = snap["mst"]
        return (
            snap["port_aw"],
            snap["port_ar"],
            m["lsu"]["aw"],
            m["lsu"]["ar"],
            m["sysif"]["aw"],
            m["sysif"]["ar"],
        )


def altered_requests(
    layout: Layout,
    out_beats,
    issued: dict,
    expect_prot: dict,
    grade: SepSrcIdGrade,
    issued_user: dict,
) -> tuple[int, int]:
    """(requests that differ from what was issued, issued requests never seen) at PR-OUT.

    ``issued`` maps ``(init, kind)`` to the list of addresses issued;
    ``expect_prot`` maps an initiator to the AxPROT the SMU path delivers, or is
    absent for an initiator whose attributes are not graded here. A request
    differs when its address is not an issued one, its AxLEN is not 0, its
    AxPROT is not the expected one, or ``grade`` refuses its AxUSER (the SMU
    path sets SEP's ID, which has no stated number). ``issued_user`` maps an
    address to the AxUSER the bench issued at it.
    """
    seen: dict = {k: Counter() for k in issued}
    altered = 0
    for beat in out_beats:
        if beat.ch not in ("aw", "ar"):
            continue
        addr = beat.fields.get("addr")
        init = layout.owner(addr)
        kind = "wr" if beat.ch == "aw" else "rd"
        key = (init, kind)
        if key not in seen or addr not in issued[key]:
            altered += 1
            continue
        seen[key][addr] += 1
        if beat.fields.get("len") != 0:
            altered += 1
            continue
        if init in expect_prot:
            bad_prot = beat.fields.get("prot") != expect_prot[init]
            bad_user = grade.note(beat.fields.get("user"), issued_user.get(addr)) is not None
            if bad_prot or bad_user:
                altered += 1
    missing = 0
    for key, addrs in issued.items():
        want = Counter(addrs)
        for addr, n in want.items():
            if seen[key][addr] < n:
                missing += n - seen[key][addr]
    return altered, missing
