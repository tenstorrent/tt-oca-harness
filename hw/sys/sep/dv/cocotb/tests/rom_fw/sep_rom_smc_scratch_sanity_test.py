# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC access sanity check on a boot to the hand-off: four scratch[7] write/read-back pairs, then
the restore to zero.

rom.adoc, SMC Synchronization, SMC Access Sanity Check:

    Before any protocol decision depends on the SMC, the ROM proves the outbound path works:
    four patterns (`0xA5A55A5A`, `0x12345678`, `0x00000000`, `0xFFFFFFFF`) are written to
    scratch[7] and read back. [SEP-ROM-SMC-020] A read-back mismatch is fatal
    (`ROM_ERR_SMC_SANITY_FAILED`, `0xA001`); the register shall be restored to zero on
    success.

scratch[7] is at SMC window offset `0x39080 + 8·7` (tbl:smc_scratch), seen from the SEP at
`SEP_SMC_GLOBAL_BASE` `0x40000000` plus that offset (tbl:smc_window).

* CHK-SANITY-WRITES: the first four scratch[7] writes carry the four spec patterns, each
  with all four byte strobes of the 32-bit register.
* CHK-SANITY-READBACKS: each of those writes is read back after it and before the next
  scratch[7] write, with an OKAY response whose data equals the written pattern.
* CHK-SANITY-RESTORE: after the fourth read-back, the last scratch[7] write up to the hand-off
  `mret` is zero, and the SMC responder holds zero in scratch[7] at the end of the run.

SMC-020 is covered in the positive direction only: the mismatch path (`0xA001` fatal) is not
graded here. The spec lists the patterns without an order, so the order is logged, not graded.
Also not graded: "before any protocol decision depends on the SMC", and the debug-console
markers of the check.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from rom_fw.sep_rom_observe_base import sep_rom_observe_base

_SMC_WINDOW = 0x4000_0000
_SCRATCH7 = _SMC_WINDOW + 0x39080 + 8 * 7
_SPEC_PATTERNS: tuple[int, ...] = (0xA5A5_5A5A, 0x1234_5678, 0x0000_0000, 0xFFFF_FFFF)
_SPEC_RESTORE = 0
_WORD = 0xFFFF_FFFF
# The 32-bit register sits in byte lanes 0..3 of the 64-bit SMC data bus.
_LANE_STRB = 0xF
_DATA64 = (1 << 64) - 1
_ID6 = 0x3F
_AXI_OKAY = 0
_OK_MARKER = "SMC_MEM_OK"


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _is_scratch7(beat) -> bool:
    return beat.addr is not None and beat.addr & ~7 == _SCRATCH7


@dataclass
class _RBeat:
    """One R handshake on the SMC responder interface, with scratch[7] as the responder holds it."""

    t_ps: int
    id: int | None
    data: int | None
    resp: int | None
    last: int | None
    held: int


def _val(sig, mask: int) -> int | None:
    v = sig.value
    return int(v) & mask if v.is_resolvable else None


def _bursts(w_beats: list) -> list[list]:
    """W beats grouped into bursts by WLAST."""
    out, cur = [], []
    for b in w_beats:
        cur.append(b)
        if b.last == 1:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _r_by_ar(ar_beats: list, r_beats: list) -> dict[int, list]:
    """R burst of each AR, keyed by the AR beat seq: AXI returns same-ID reads in AR order."""
    queues: dict[int | None, list[list]] = defaultdict(list)
    cur: dict[int | None, list] = defaultdict(list)
    for r in r_beats:
        cur[r.id].append(r)
        if r.last == 1:
            queues[r.id].append(cur.pop(r.id))
    out = {}
    for ar in ar_beats:
        q = queues.get(ar.id)
        if q:
            out[ar.seq] = q.pop(0)
    return out


@pyuvm.test()
class sep_rom_smc_scratch_sanity_test(sep_rom_observe_base):
    required_evidence = ("CHK-SANITY-WRITES", "CHK-SANITY-READBACKS", "CHK-SANITY-RESTORE")

    def done(self, obs) -> bool:
        return obs.post_mret is not None or obs.verdict_pass() is not None

    async def run_scenario(self) -> None:
        # The tap and the R monitor start before reset release so the first SMC access is recorded.
        self.smc = SepFabricTap("PR-SMC").start()
        self.mark = self.smc.mark()
        self.r_beats: list[_RBeat] = []
        self._r_run = True
        self._r_task = cocotb.start_soon(self._watch_r())
        await super().run_scenario()

    async def _watch_r(self) -> None:
        """Record R handshakes, which the PR-SMC tap does not carry."""
        dut = cocotb.top
        bus = dut.u_smc_axi_if
        mem = self.cfg.smc_mem
        while self._r_run:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            valid, ready = _val(bus.rvalid, 1), _val(bus.rready, 1)
            if valid is None or ready is None:
                raise AssertionError(
                    f"SMC R handshake is X/Z at {get_sim_time('ps')}ps; "
                    "check u_smc_axi_if rvalid/rready wiring"
                )
            if valid and ready:
                self.r_beats.append(
                    _RBeat(
                        int(get_sim_time("ps")),
                        _val(bus.rid, _ID6),
                        _val(bus.rdata, _DATA64),
                        _val(bus.rresp, 3),
                        _val(bus.rlast, 1),
                        mem.read32(_SCRATCH7),
                    )
                )

    async def before_grade(self, obs) -> None:
        self._r_run = False
        await RisingEdge(cocotb.top.clk_i)
        await RisingEdge(cocotb.top.clk_i)
        if not self._r_task.done() or self._r_task.exception() is not None:
            raise AssertionError(
                f"SMC R monitor did not end cleanly: {self._r_task}; fix the exception it "
                "raised, or the stop handshake in before_grade if it is still running"
            )
        await self.smc.stop()

    def grade(self, obs, chk) -> None:
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        end_t = mret.t_ps if mret is not None and obs.post_mret is not None else None
        chk.ctrl(
            "HANDOFF",
            end_t is not None and obs.verdict_pass() is not False,
            handoff_ps=end_t if end_t is not None else -1,
            bl1_pc=_hex(obs.post_mret.pc if obs.post_mret else None),
        )

        beats = self.smc.since(self.mark)
        aw = [b for b in beats if b.ch == "aw"]
        ar = [b for b in beats if b.ch == "ar"]
        wb = _bursts([b for b in beats if b.ch == "w"])
        r_of = _r_by_ar(ar, self.r_beats)
        unknown = sum(1 for b in beats if b.has_unknown()) + sum(
            1 for r in self.r_beats if None in (r.id, r.data, r.resp, r.last)
        )
        # AW and W pair in order (AXI4 has no WID); every AR has its R burst.
        chk.ctrl(
            "SMC-RECORD-LIVE",
            bool(aw) and len(aw) == len(wb) and bool(ar) and len(r_of) == len(ar) and not unknown,
            aw=len(aw),
            w_bursts=len(wb),
            ar=len(ar),
            r_beats=len(self.r_beats),
            ar_answered=len(r_of),
            unknown=unknown,
        )

        def in_rom(t: int) -> bool:
            return end_t is not None and t <= end_t

        # (time, 32-bit lane data, lane strobes) of each scratch[7] write up to the hand-off.
        writes = []
        for a, burst in zip(aw, wb, strict=False):
            if _is_scratch7(a) and in_rom(a.t_ps):
                w = burst[0]
                data = None if w.data is None else w.data & _WORD
                strb = None if w.strb is None else w.strb & _LANE_STRB
                writes.append((a.t_ps, data, strb))
        reads = []
        for a in ar:
            if _is_scratch7(a) and in_rom(a.t_ps):
                r = (r_of.get(a.seq) or [None])[0]
                reads.append((a.t_ps, r))
        late = [b.fmt() for b in aw if _is_scratch7(b) and not in_rom(b.t_ps)]
        chk.obs(
            "SCRATCH7-ACCESSES",
            addr=_hex(_SCRATCH7),
            writes=[_hex(d) for _, d, _ in writes],
            reads=[_hex(None if r is None else r.data & _WORD) for _, r in reads],
            after_handoff=late,
            ok_marker_ps=obs.line_t(_OK_MARKER) or -1,
        )

        pairs = []
        for i, (t_w, data, _) in enumerate(writes[: len(_SPEC_PATTERNS)]):
            t_next = writes[i + 1][0] if i + 1 < len(writes) else None
            rb = [r for t, r in reads if t > t_w and (t_next is None or t < t_next)]
            pairs.append((data, rb))

        # The responder's backdoor word at each read-back equals the paired W lane data.
        lane = [
            (data, rb[0].held)
            for data, rb in pairs
            if rb and rb[0] is not None and data is not None
        ]
        chk.ctrl(
            "SCRATCH7-LANE",
            len(lane) == len(_SPEC_PATTERNS)
            and all(d == h for d, h in lane)
            and any(d not in (0, _WORD) for d, _ in lane),
            pairs=[f"{_hex(d)}:{_hex(h)}" for d, h in lane],
        )

        first = writes[: len(_SPEC_PATTERNS)]
        chk.ok(
            "SANITY-WRITES",
            len(first) == len(_SPEC_PATTERNS)
            and Counter(d for _, d, _ in first) == Counter(_SPEC_PATTERNS)
            and all(s == _LANE_STRB for _, _, s in first),
            written=[_hex(d) for _, d, _ in first],
            strobes=[_hex(s) for _, _, s in first],
            spec=[_hex(p) for p in _SPEC_PATTERNS],
        )

        def read_ok(data, rb) -> bool:
            return (
                bool(rb)
                and data is not None
                and all(
                    r is not None and r.resp == _AXI_OKAY and r.data & _WORD == data for r in rb
                )
            )

        chk.ok(
            "SANITY-READBACKS",
            len(pairs) == len(_SPEC_PATTERNS) and all(read_ok(d, rb) for d, rb in pairs),
            pairs=[
                f"{_hex(d)}->"
                + "/".join("none" if r is None else f"{_hex(r.data & _WORD)}:{r.resp}" for r in rb)
                for d, rb in pairs
            ],
        )

        after = writes[len(_SPEC_PATTERNS) :]
        held = self.cfg.smc_mem.read32(_SCRATCH7)
        chk.ok(
            "SANITY-RESTORE",
            bool(after)
            and after[-1][1] == _SPEC_RESTORE
            and after[-1][2] == _LANE_STRB
            and not late
            and held == _SPEC_RESTORE,
            writes_after_pairs=[_hex(d) for _, d, _ in after],
            responder_scratch7=_hex(held),
            spec=_hex(_SPEC_RESTORE),
        )
