# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DCCM contents are written before the C runtime reads them, graded on the DCCM macro port.

rom.adoc, Cold Boot Environment Setup:

* SEP-ROM-CPU-160: "The ROM shall leave DCCM in a deterministic state before the C runtime
  reads it, so that no uninitialized-ECC read and no stale value from a previous boot reaches
  the boot flow. The stub zero-fills DCCM from its base up to at most `__stack_top`. The scrub
  length is a build-time knob (`DCCM_SCRUB_BYTES`, default 128 KiB = full DCCM); `0` disables
  the scrub and is a simulation-preload configuration only, not a product one."
* "The stub then calls `rom_main()`."

CPU-160 is covered in part. The C runtime starts at the first retirement of `rom_main`.
Every DCCM read from reset to the hand-off mret must hit a word written earlier in the run and
return the data and ECC of that last write, and every word in [DCCM base, `__stack_top`) must be
written with zero before the C runtime starts. The upper bound "at most `__stack_top`" is not
graded: the same item and its neighbours also say the scrub writes the full 128 KiB and place
`bl0_state` above `__stack_top`, so only the lower range is undisputed; an OBS counts the zero
writes above `__stack_top`. The build-time knob and its `0` setting are not graded; a CTRL
shows from the trace that the scrub loop of this build reaches `__stack_top`.
Double-bit ECC errors are planted with the TCM bit-flip hook while `rst_ni` is low. The tb
logs each flip, and the CTRL shows that every pulse ended before reset release; the stored
words are not readable from cocotb. PLANTED-NOT-REACHED is the planted-word subset of
READ-LAST-WRITE. The X checks of the tap are inert on 2-state Verilator.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, load_rom_syms
from env.sep_rv32_trace_decode import INSN_MRET, funct3, is_store
from env.sep_seeded_rng import SepSeededRng
from env.sep_tcm_flip import DATA_BITS, DCCM_BASE, DCCM_BYTES, ECC_BITS, bit_mask, tcm_flip
from rom_fw.sep_rom_observe_base import sep_rom_observe_base

# PR-TCM DCCM geometry: 2 banks, bank = byte offset bit 2, row = byte offset bits 16:3.
_BANKS = 2
_AW = 14
_C_ENTRY_SYM = "rom_main"
# Runtime-check globals that rom_main reads; a planted error there must not reach the read.
_READ_SYMS = ("g_data_init", "g_bss_zero")
_STACK_FLIPS = 2
_RANDOM_FLIPS = 2
_MIN_PROBES = 16
_DCCM_END = DCCM_BASE + DCCM_BYTES
# Scrub-loop store encoding (sw zero, 0(t0)); SCRUB-BOUND fails if the ROM changes it.
_SCRUB_SW = 0x0002A023


def _slot(addr: int) -> tuple[int, int]:
    off = addr - DCCM_BASE
    return (off >> 2) & (_BANKS - 1), off >> 3


def _addr(slot: tuple[int, int]) -> int:
    bank, row = slot
    return DCCM_BASE + (row << 3) + (bank << 2)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


@pyuvm.test()
class sep_rom_dccm_scrub_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-DCCM-WRITE-BEFORE-READ",
        "CHK-DCCM-SPEC-RANGE-WRITTEN",
        "CHK-DCCM-READ-LAST-WRITE",
        "CHK-DCCM-PLANTED-NOT-REACHED",
    )

    @property
    def observer_kwargs(self) -> dict:
        return {"pc_watch": frozenset({self.syms[_C_ENTRY_SYM]})}

    def _draw_flips(self) -> dict[int, int]:
        """Planted double-bit errors: byte address -> 39-bit mask."""
        rng = SepSeededRng(self.random_seed())
        top = self.syms["__stack_top"]
        addrs = [self.syms[n] for n in _READ_SYMS]
        while len(addrs) < len(_READ_SYMS) + _STACK_FLIPS:
            a = top - 4 * (1 + rng.randrange(64))
            if a not in addrs:
                addrs.append(a)
        while len(addrs) < len(_READ_SYMS) + _STACK_FLIPS + _RANDOM_FLIPS:
            a = DCCM_BASE + 4 * rng.randrange((top - DCCM_BASE) // 4)
            if a not in addrs:
                addrs.append(a)
        return {a: bit_mask(*rng.sample(range(DATA_BITS), 2)) for a in addrs}

    async def run_scenario(self) -> None:
        self.syms = load_rom_syms()
        self.flips = self._draw_flips()
        self.flip_rst_low: list[bool] = []
        self.flip_end_ps: int | None = None
        self.tap_start_ps = int(get_sim_time("ps"))
        self.tcm = SepFabricTap("PR-TCM").start()
        self.mark = self.tcm.mark()
        await super().run_scenario()

    async def stimulus(self, obs) -> None:
        # The clock starts with rst_ni low, so the flips land before reset release.
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        self.flip_rst_low.append(self.rd(dut.rst_ni) == 0)
        for addr, mask in self.flips.items():
            await tcm_flip(dut, addr, mask)
        self.flip_rst_low.append(self.rd(dut.rst_ni) == 0)
        self.flip_end_ps = int(get_sim_time("ps"))

    async def before_grade(self, obs) -> None:
        self.tap_stop_ps = int(get_sim_time("ps"))
        await self.tcm.stop()

    def _walk(self, end_t: int | None, c_t: int | None) -> dict:
        """One pass over the DCCM beats up to end_t, in record order."""
        written: dict[tuple[int, int], tuple[int | None, int | None]] = {}
        # slot -> (write times, write data), both in time order
        wbeats: dict[tuple[int, int], tuple[list[int], list[int | None]]] = {}
        first_t = self.obs.first[0].t_ps if self.obs.first else None
        early_writes = 0
        zero_before_c: set[tuple[int, int]] = set()
        planted = {_slot(a) for a in self.flips}
        w = {"writes": 0, "reads": 0, "unknown": 0, "rsp": 0, "unpaired": 0}
        unwritten: list[tuple[int, tuple[int, int]]] = []
        planted_reads: dict[tuple[int, int], list[tuple[int, bool]]] = {s: [] for s in planted}
        mismatches: list[tuple[int, tuple[int, int]]] = []
        recent: list[tuple[int, list]] = []
        for b in self.tcm.since(self.mark):
            if end_t is not None and b.t_ps > end_t:
                break
            if b.ch == "dccm":
                issued = []
                for bank in range(_BANKS):
                    en = b.lane("clken", bank, 1)
                    if not en:
                        w["unknown"] += en is None
                        continue
                    we = b.lane("wren", bank, 1)
                    row = b.lane("addr", bank, _AW)
                    if we is None or row is None:
                        w["unknown"] += 1
                        continue
                    slot = (bank, row)
                    if we:
                        data = b.lane("wdata", bank, DATA_BITS)
                        written[slot] = (data, b.lane("wecc", bank, ECC_BITS))
                        times, data_words = wbeats.setdefault(slot, ([], []))
                        times.append(b.t_ps)
                        data_words.append(data)
                        w["writes"] += 1
                        early_writes += first_t is None or b.t_ps < first_t
                        if data == 0 and c_t is not None and b.t_ps < c_t:
                            zero_before_c.add(slot)
                    else:
                        w["reads"] += 1
                        if slot not in written:
                            unwritten.append((b.t_ps, slot))
                        issued.append((bank, slot, written.get(slot)))
                if issued:
                    recent = (recent + [(b.t_ps, issued)])[-2:]
            elif b.ch == "dccm_rsp":
                w["rsp"] += 1
                # The response belongs to the latest read issued on an earlier clock.
                req = next((r for t, r in reversed(recent) if t < b.t_ps), None)
                if req is None:
                    w["unpaired"] += 1
                    continue
                recent = [(t, r) for t, r in recent if t >= b.t_ps]
                for bank, slot, expect in req:
                    got = (b.lane("rdata", bank, DATA_BITS), b.lane("recc", bank, ECC_BITS))
                    same = expect is not None and got == expect
                    if not same:
                        mismatches.append((b.t_ps, slot))
                    if slot in planted_reads:
                        planted_reads[slot].append((b.t_ps, same))
        return {
            **w,
            "wbeats": wbeats,
            "zero_before_c": zero_before_c,
            "unwritten": unwritten,
            "planted_reads": planted_reads,
            "mismatches": mismatches,
            "early_writes": early_writes,
        }

    @staticmethod
    def _probe_matches(probes, wbeats, slot_of, win_ps: int) -> int:
        """Probes whose stored word appears on slot_of(addr) within win_ps of the retirement."""
        hits = 0
        for r in probes:
            times, data_words = wbeats.get(slot_of(r.mem_addr), ((), ()))
            lo, hi = bisect_left(times, r.t_ps - win_ps), bisect_right(times, r.t_ps + win_ps)
            hits += r.mem_data in data_words[lo:hi]
        return hits

    def grade(self, obs, chk) -> None:
        syms = self.syms
        top = syms["__stack_top"]
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        end_t = mret.t_ps if mret is not None and mret.insn == INSN_MRET else None
        live = end_t is not None and obs.post_mret is not None and obs.verdict_pass() is True
        chk.ctrl(
            "HANDOFF",
            live,
            handoff_ps=end_t if end_t is not None else -1,
            bl1_pc=_hex(obs.post_mret.pc if obs.post_mret else None),
            verdict=obs.verdict_pass(),
        )
        c_hits = [t for t, pc in obs.pc_hits if pc == syms[_C_ENTRY_SYM]]
        c_t = c_hits[0] if c_hits else None
        chk.ctrl(
            "C-ENTRY",
            c_t is not None and live and c_t < end_t,
            sym=_C_ENTRY_SYM,
            pc=_hex(syms[_C_ENTRY_SYM]),
            c_ps=c_t if c_t is not None else -1,
            hits=len(c_hits),
        )

        first_t = obs.first[0].t_ps if obs.first else None
        chk.ctrl(
            "FLIPS-BEFORE-RESET",
            self.flip_rst_low == [True, True]
            and self.flip_end_ps is not None
            and first_t is not None
            and self.flip_end_ps < first_t,
            flips=len(self.flips),
            rst_low=self.flip_rst_low,
            flip_end_ps=self.flip_end_ps if self.flip_end_ps is not None else -1,
            first_retire_ps=first_t if first_t is not None else -1,
            planted=[f"{_hex(a)}^0x{m:010x}" for a, m in self.flips.items()],
        )

        walk = self._walk(end_t if live else None, c_t)
        beats = self.tcm.since(self.mark, "dccm")
        sample = next((b for b in beats if b.raw), None)
        geometry = (
            sample is not None
            and len(sample.raw["clken"]) == _BANKS
            and len(sample.raw["addr"]) == _BANKS * _AW
            and len(sample.raw["wdata"]) == _BANKS * DATA_BITS
            and DCCM_BYTES == _BANKS * (1 << _AW) * 4
        )
        tcm_live = (
            live
            and first_t is not None
            and self.tap_start_ps <= first_t
            and self.tap_stop_ps >= end_t
            and walk["writes"] > 0
            and walk["reads"] > 0
            and walk["unknown"] == 0
            and walk["unpaired"] == 0
            and walk["rsp"] > 0
        )
        chk.ctrl(
            "TCM-LIVE",
            tcm_live,
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            writes=walk["writes"],
            reads=walk["reads"],
            rsp=walk["rsp"],
            unknown=walk["unknown"],
            unpaired=walk["unpaired"],
        )

        # A sw of a known nonzero word lands on its slot near its retirement; a wrong map misses.
        win_ps = STORE_LAG_MAX_CYCLES * int(round(self.cfg.sys_clk_period_ns * 1000))
        stores = [
            r
            for r in obs.retires
            if is_store(r.insn)
            and not (r.exc or r.interrupt)
            and r.mem_addr is not None
            and DCCM_BASE <= r.mem_addr < DCCM_BASE + DCCM_BYTES
            and (end_t is None or r.t_ps <= end_t)
        ]
        by_word: dict[int, list[int]] = {}
        for r in stores:
            by_word.setdefault(r.mem_addr & ~3, []).append(r.t_ps)

        def coalesces(r) -> bool:
            # A later store to the same word within the window may merge with the probe.
            times = by_word[r.mem_addr & ~3]
            return bisect_right(times, r.t_ps + win_ps) > bisect_right(times, r.t_ps)

        probes = [
            r
            for r in stores
            if funct3(r.insn) == 2 and r.mem_data and r.mem_addr % 4 == 0 and not coalesces(r)
        ]
        wbeats = walk["wbeats"]
        matched = self._probe_matches(probes, wbeats, _slot, win_ps)
        swap = self._probe_matches(probes, wbeats, lambda a: (_slot(a)[0] ^ 1, _slot(a)[1]), win_ps)
        word = self._probe_matches(
            probes, wbeats, lambda a: (_slot(a)[0], (a - DCCM_BASE) >> 2), win_ps
        )
        slot_ok = (
            geometry
            and len(probes) >= _MIN_PROBES
            and matched == len(probes)
            and swap < len(probes)
            and word < len(probes)
        )
        chk.ctrl(
            "SLOT-MAP",
            slot_ok,
            geometry=geometry,
            probes=len(probes),
            matched=matched,
            bank_swapped=swap,
            word_index=word,
            window_ps=win_ps,
        )

        unwritten = walk["unwritten"]
        before_c = sum(1 for t, _ in unwritten if c_t is None or t < c_t)
        chk.ok(
            "DCCM-WRITE-BEFORE-READ",
            tcm_live and slot_ok and not unwritten,
            reads=walk["reads"],
            unwritten=len(unwritten),
            unwritten_before_c=before_c,
            first=[f"{_hex(_addr(s))}@{t}" for t, s in unwritten[:4]],
        )

        mism = walk["mismatches"]
        chk.ok(
            "DCCM-READ-LAST-WRITE",
            tcm_live and slot_ok and not mism,
            reads=walk["reads"],
            mismatches=len(mism),
            first=[f"{_hex(_addr(s))}@{t}" for t, s in mism[:4]],
        )

        # The scrub bound of this build: the span the scrub-loop stores cover in the trace.
        scrub = next(
            (
                r
                for r in obs.retires
                if r.insn == _SCRUB_SW and r.mem_addr == DCCM_BASE and not (r.exc or r.interrupt)
            ),
            None,
        )
        loop = [r.mem_addr for r in obs.retires if scrub is not None and r.pc == scrub.pc]
        known = [a for a in loop if a is not None]
        scrub_end = max(known) + 4 if known else None
        chk.ctrl(
            "SCRUB-BOUND",
            scrub is not None
            and len(known) == len(loop)
            and len(set(known)) == len(known) == (scrub_end - DCCM_BASE) // 4
            and scrub_end >= top,
            scrub_pc=_hex(scrub.pc if scrub else None),
            stores=len(loop),
            unresolved=len(loop) - len(known),
            end=_hex(scrub_end),
            stack_top=_hex(top),
        )

        need = [_slot(a) for a in range(DCCM_BASE, top, 4)]
        missing = [s for s in need if s not in walk["zero_before_c"]]
        chk.ok(
            "DCCM-SPEC-RANGE-WRITTEN",
            tcm_live and slot_ok and c_t is not None and need and not missing,
            range=f"[{_hex(DCCM_BASE)},{_hex(top)})",
            words=len(need),
            zero_written=len(need) - len(missing),
            missing=len(missing),
            first_missing=[_hex(_addr(s)) for s in missing[:4]],
        )

        preads = walk["planted_reads"]
        must_read = [_slot(syms[n]) for n in _READ_SYMS]
        read_after_c = all(
            any(c_t is not None and t >= c_t for t, _ in preads.get(s, [])) for s in must_read
        )
        chk.ctrl(
            "PLANTED-READ",
            read_after_c,
            syms=list(_READ_SYMS),
            reads=[f"{_hex(_addr(s))}:{len(preads.get(s, []))}" for s in must_read],
        )
        stale = [_addr(s) for s, rs in preads.items() if not all(same for _, same in rs)]
        chk.ok(
            "DCCM-PLANTED-NOT-REACHED",
            live and tcm_live and slot_ok and read_after_c and not stale,
            planted=len(self.flips),
            reads=sum(len(rs) for rs in preads.values()),
            stale=[_hex(a) for a in stale],
        )
        chk.obs(
            "DCCM-READS",
            above_stack_top_zero_before_c=sum(
                _slot(a) in walk["zero_before_c"] for a in range(top, _DCCM_END, 4)
            ),
            above_stack_top_words=(_DCCM_END - top) // 4,
            writes_before_first_retire=walk["early_writes"],
        )
