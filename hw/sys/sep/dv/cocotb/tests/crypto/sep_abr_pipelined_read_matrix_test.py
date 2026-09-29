# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pipelined reads of the Adams Bridge aperture each return their own address.

no_cpu / +skip_fuse_sense.

An AXI-to-AHB bridge that streams reads can present the later transfers of a
stream with a truncated HADDR. Every read still answers OKAY, so a lone read
cannot show the defect; it takes several reads in flight at once, each graded
against the value of the address it named. Through such a bridge an odd word
such as MLDSA_VERSION1 at 0x1094_000c reads back the wrong word from the third
read of a pipeline onward, because HADDR[2:0] is dropped.

The RDL and the SEP documents give no identity value, so ``CHK-ABR-ID-REF``
first reads each identity word alone on s_axi, and that capture is the value
every read below is graded against.

Legs, all run before the verdict so one run names every leg that fails:

1. One read of MLDSA_VERSION1 on each master: the control.
2. Concurrent single-beat reads of MLDSA_VERSION1 at depths 1, 2, 3, 4 and 8,
   one ARID each, first on m_axi (the SMN inbound master, through an
   inbound-filter read window over the ABR aperture) and then on s_axi.
3. The four ML-DSA identity words in several orders, each read graded against
   its own word, on both masters, plus one order on a single ARID.
4. Both masters pipelining at once.

Each leg records the AR and R handshakes on the TB pins. Concurrency is graded
from that record: on a distinct-ID leg every request must have been accepted
before the first response came back, and on the single-ARID leg at least
three. Each R beat is graded by the RID it carried as well as through the VIP's
result, so a response that comes back under the wrong ID fails even when every
request named the same address.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_abr_bus_seq import (
    ID_WIDTH,
    IDENTITY,
    RESP_OKAY,
    AbrAccess,
    AbrBusWatch,
    SepAbrBus,
    lane_value,
)
from seq_lib.sep_abr_keygen_seq import ABR_NAME0, ABR_NAME1, ABR_VERSION0, ABR_VERSION1

DEPTHS = (1, 2, 3, 4, 8)

# Reads on one ARID that must be accepted before the first response. The
# fabric bounds how many transactions of a single ID it holds, which is a
# different limit from the distinct-ID legs, where every read must be accepted
# first. Three is the shallowest pipeline at which a bridge that drops
# HADDR[2:0] on its streamed transfers returns a wrong word.
SAME_ID_FLOOR = 3

N0, N1, V0, V1 = ABR_NAME0, ABR_NAME1, ABR_VERSION0, ABR_VERSION1
MIXED_ORDERS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("ascending", (N0, N1, V0, V1)),
    ("descending", (V1, V0, N1, N0)),
    ("even-words-first", (N0, V0, N1, V1)),
    ("interleaved-8", (V1, N0, N1, V1, V0, N1, N0, V1)),
)
SAME_ID_ORDER = (N0, V0, V1, N1)

_NAMES = {N0: "NAME0", N1: "NAME1", V0: "VERSION0", V1: "VERSION1"}


def _selftest() -> None:
    assert V1 - N0 == 0xC, "MLDSA_VERSION1 is the odd word of the second granule"
    for _name, order in MIXED_ORDERS + (("same-id", SAME_ID_ORDER),):
        # A pipeline shorter than three never reaches a streamed transfer.
        assert len(order) >= 3
        assert all(a in IDENTITY for a in order)
        # Dropping HADDR[2:0] only changes an odd word, so each order puts one
        # at the third position or later.
        assert any(a & 0x4 for a in order[2:]), _name
    # Depth 8 needs eight distinct IDs on the narrower of the two ports.
    assert max(DEPTHS) <= 1 << min(ID_WIDTH.values())
    assert SAME_ID_FLOOR <= len(SAME_ID_ORDER)


_selftest()


@pyuvm.test()
class sep_abr_pipelined_read_matrix_test(sep_base_test):
    """Concurrent ABR reads, on each master and both, return their own words."""

    required_evidence = (
        "CHK-ABR-ID-REF",
        "CHK-ABR-PIPE-CTRL",
        "CHK-ABR-PIPE-DEPTH-M-AXI",
        "CHK-ABR-PIPE-DEPTH-S-AXI",
        "CHK-ABR-PIPE-MIXED",
        "CHK-ABR-PIPE-SAME-ID",
        "CHK-ABR-PIPE-DUAL",
        "CHK-ABR-PIPE-RID",
        "CHK-ABR-PIPE-OVERLAP",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.abr = SepAbrBus(self)
        await self.abr.capture_identity("s_axi")
        await self.abr.open_m_axi_window(write=False)

        self.failures: list[str] = []
        self.rid_problems: list[str] = []
        self.overlap_problems: list[str] = []

        # --- CHK-ABR-PIPE-CTRL ----------------------------------------------
        # One read at a time is the case every bridge gets right, so a failure
        # here is a path or decode problem and not the pipelining under test.
        for bus in ("m_axi", "s_axi"):
            acc = await self.abr.read(bus, V1)
            self.logger.info("ABR-PIPE control: %s", acc.describe())
            assert acc.resp == RESP_OKAY and acc.data == IDENTITY[V1].value, (
                f"CHK-ABR-PIPE-CTRL FAIL: lone read of MLDSA_VERSION1 on {bus} returned "
                f"{acc.resp_name} 0x{acc.data:08x}, expected OKAY "
                f"0x{IDENTITY[V1].value:08x}; the pipelined legs need a working single read"
            )
        self.logger.info(
            "CHK-ABR-PIPE-CTRL PASS: a lone read of MLDSA_VERSION1 returns 0x%08x OKAY on "
            "m_axi and on s_axi",
            IDENTITY[V1].value,
        )

        # --- CHK-ABR-PIPE-DEPTH-* ---------------------------------------------
        for bus, chk in (
            ("m_axi", "CHK-ABR-PIPE-DEPTH-M-AXI"),
            ("s_axi", "CHK-ABR-PIPE-DEPTH-S-AXI"),
        ):
            ok = True
            for depth in DEPTHS:
                ok &= await self._leg(
                    f"{bus} VERSION1 x{depth}", {bus: [(V1, i) for i in range(depth)]}
                )
            if ok:
                self.logger.info(
                    "%s PASS: %s depths %s of concurrent MLDSA_VERSION1 reads each "
                    "returned 0x%08x OKAY",
                    chk,
                    bus,
                    ",".join(str(d) for d in DEPTHS),
                    IDENTITY[V1].value,
                )

        # --- CHK-ABR-PIPE-MIXED -----------------------------------------------
        ok = True
        for bus in ("m_axi", "s_axi"):
            for name, order in MIXED_ORDERS:
                ok &= await self._leg(f"{bus} {name}", {bus: [(a, i) for i, a in enumerate(order)]})
        if ok:
            self.logger.info(
                "CHK-ABR-PIPE-MIXED PASS: %d address orders on each master; every read "
                "returned the identity word it named",
                len(MIXED_ORDERS),
            )

        # --- CHK-ABR-PIPE-SAME-ID ---------------------------------------------
        # One ID orders the responses, so the k-th response belongs to the
        # k-th request: a path that reorders same-ID reads hands each request
        # a neighbour's word.
        ok = True
        for bus in ("m_axi", "s_axi"):
            same = (1 << ID_WIDTH[bus]) - 1
            ok &= await self._leg(
                f"{bus} same-id",
                {bus: [(a, same) for a in SAME_ID_ORDER]},
                need=SAME_ID_FLOOR,
            )
        if ok:
            self.logger.info(
                "CHK-ABR-PIPE-SAME-ID PASS: %d reads on one ARID per master returned "
                "their own words in request order",
                len(SAME_ID_ORDER),
            )

        # --- CHK-ABR-PIPE-DUAL ------------------------------------------------
        order = dict(MIXED_ORDERS)["interleaved-8"]
        both = {
            "m_axi": [(a, 8 + i) for i, a in enumerate(order)],
            "s_axi": [(a, i) for i, a in enumerate(reversed(order))],
        }
        if await self._leg("dual interleaved-8", both):
            self.logger.info(
                "CHK-ABR-PIPE-DUAL PASS: m_axi and s_axi pipelining %d reads each at the "
                "same time; every read returned its own word",
                len(order),
            )

        if not self.rid_problems:
            self.logger.info(
                "CHK-ABR-PIPE-RID PASS: on every leg each R beat carried the RID of an "
                "outstanding request, once per request"
            )
        if not self.overlap_problems:
            self.logger.info(
                "CHK-ABR-PIPE-OVERLAP PASS: every read of each distinct-ID leg, and %d "
                "of each single-ARID leg, was accepted before the first response; both "
                "masters were in flight together on the dual leg",
                SAME_ID_FLOOR,
            )

        problems = self.failures + self.rid_problems + self.overlap_problems
        assert not problems, (
            f"ABR-PIPE FAIL: {len(problems)} problem(s) across the pipelined legs: "
            + " | ".join(problems)
        )

    async def _leg(
        self, leg: str, plan: dict[str, list[tuple[int, int]]], *, need: int | None = None
    ) -> bool:
        """Issue every read in ``plan`` at once and grade it. True when clean.

        ``need`` is how many reads per master must be accepted before the first
        response; all of them when omitted.
        """
        accs = {
            bus: [AbrAccess(bus, "rd", addr, axi_id=axi_id, tag=leg) for addr, axi_id in reqs]
            for bus, reqs in plan.items()
        }
        watch = AbrBusWatch(tuple(accs))
        watch.start()
        flat = [a for bus_accs in accs.values() for a in bus_accs]
        try:
            await self.abr.all_at_once(flat)
        finally:
            watch.stop()

        clean = True
        for bus, bus_accs in accs.items():
            rec = watch.rec[bus]
            data_bad = self._grade_data(leg, bus, bus_accs)
            data_bad += self._grade_beats(leg, bus, bus_accs, rec)
            if data_bad:
                got = ", ".join(f"0x{a.data:08x}" for a in bus_accs)
                exp = ", ".join(f"0x{IDENTITY[a.addr].value:08x}" for a in bus_accs)
                self.logger.error(
                    "ABR-PIPE FAIL [%s] %s: returned [%s], expected [%s]", leg, bus, got, exp
                )
                self.failures.append(f"[{leg}] {bus}: {data_bad[0]}")
                clean = False
            floor = len(bus_accs) if need is None else min(need, len(bus_accs))
            self.logger.info(
                "ABR-PIPE [%s] %s concurrency: %d AR accepted before the first R "
                "(need %d), max %d outstanding",
                leg,
                bus,
                rec.ar_before_first_r,
                floor,
                rec.max_rd_outstanding,
            )
            if rec.ar_before_first_r < floor:
                self.overlap_problems.append(
                    f"[{leg}] {bus}: only {rec.ar_before_first_r} of {len(bus_accs)} reads "
                    f"accepted before the first response, need {floor}; the leg did not "
                    "pipeline and its data compare proves nothing about pipelining"
                )
                clean = False
        if len(accs) > 1:
            self.logger.info(
                "ABR-PIPE [%s] cycles with every master outstanding: %d",
                leg,
                watch.all_busy_cycles,
            )
            if watch.all_busy_cycles == 0:
                self.overlap_problems.append(
                    f"[{leg}] the masters were never outstanding in the same cycle"
                )
                clean = False
        return clean

    def _grade_data(self, leg: str, bus: str, accs: list[AbrAccess]) -> list[str]:
        """What the VIP handed each request against the word it named."""
        bad: list[str] = []
        for k, a in enumerate(accs):
            want = IDENTITY[a.addr].value
            verdict = "ok" if a.resp == RESP_OKAY and a.data == want else "MISMATCH"
            self.logger.info(
                "ABR-PIPE [%s] #%d %s %s expected 0x%08x %s",
                leg,
                k,
                _NAMES.get(a.addr, "?"),
                a.describe(),
                want,
                verdict,
            )
            if verdict != "ok":
                bad.append(
                    f"#{k} arid={a.axi_id} {_NAMES.get(a.addr, '?')}@0x{a.addr:08x} returned "
                    f"{a.resp_name} 0x{a.data:08x}, expected OKAY 0x{want:08x}"
                )
        return bad

    def _grade_beats(self, leg: str, bus: str, accs: list[AbrAccess], rec) -> list[str]:
        """Each R beat on the pins against the request whose ID it carried.

        Requests are matched per ID in issue order, which is the AXI ordering
        rule, so one ID with several reads outstanding is graded too.
        """
        bad: list[str] = []
        pending: dict[int, list[AbrAccess]] = {}
        for a in accs:
            pending.setdefault(a.axi_id, []).append(a)
        ar_ids = sorted(ar_id for _c, ar_id, _addr in rec.ar)
        self.logger.info(
            "ABR-PIPE [%s] %s AR order: %s",
            leg,
            bus,
            " ".join(f"id{ar_id}@0x{addr:08x}" for _c, ar_id, addr in rec.ar),
        )
        for cyc, rid, rresp, rdata in rec.r:
            queue = pending.get(rid)
            if not queue:
                self.rid_problems.append(
                    f"[{leg}] {bus}: R beat at cycle {cyc} carried RID {rid}, which no "
                    "outstanding request of this leg used"
                )
                continue
            a = queue.pop(0)
            got = lane_value(a.addr, 4, rdata if rdata >= 0 else 0)
            want = IDENTITY[a.addr].value
            self.logger.info(
                "ABR-PIPE [%s] %s R beat cycle=%d rid=%d rresp=%d lane(0x%08x)=0x%08x "
                "expected 0x%08x %s",
                leg,
                bus,
                cyc,
                rid,
                rresp,
                a.addr,
                got,
                want,
                "ok" if rresp == RESP_OKAY and got == want else "MISMATCH",
            )
            if rresp != RESP_OKAY or got != want:
                bad.append(
                    f"R beat rid={rid} for {_NAMES.get(a.addr, '?')}@0x{a.addr:08x} carried "
                    f"rresp={rresp} 0x{got:08x}, expected OKAY 0x{want:08x}"
                )
        r_ids = sorted(rid for _c, rid, _resp, _data in rec.r)
        issued = sorted(a.axi_id for a in accs)
        if r_ids != issued or ar_ids != issued:
            self.rid_problems.append(
                f"[{leg}] {bus}: issued ARIDs {issued}, accepted {ar_ids}, responses "
                f"carried RIDs {r_ids}"
            )
        return bad
