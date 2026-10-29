# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded outbound filter rule tables against JTAG probes at the output window.

Spec sources: axi_filter index.adoc (Instances; Match, Then Permit; Address Range Granule;
Blocked Transactions), fabric.adoc (Outbound Filtering; Non-Secure Bit Filtering),
filter_ctrl.rdl FILTER_CONFIG, START_ADDR and END_ADDR.

Four rule tables of 2 to 6 outbound entries (indices 0 to 15, `src_id` 0) are drawn from the
seed, each with 10 drawn JTAG probes, one pinned 2-beat burst against an `allow_burst` 0 entry
whose response turns on that term, and one pinned probe one granule outside each enabled window
whose entry clears the bit of the probe's direction, at an address that matches no entry, so the
response turns on that entry's range. The golden of every probe comes from the drawn table
alone: the entries whose match terms all hold, the lowest-numbered one and its permission bit
for the direction, or the pass of the unmatched-traffic policy when none matches. Every probe
word is a seed word preset in the SYS_OUT responder memory.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, _field_mask, reg_reset_word, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    BLOCKED_WRITE_HOLD_CYCLES,
    RESP_DECERR,
    RESP_OKAY,
    RESPONDER_OBS_TIMEOUT_CYCLES,
    check_output_responder_delta,
    output_responder_counts,
)

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_READ_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_WRITE_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_ALLOW_NS = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_ALLOW_BURST = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_RESET = {
    "FILTER_CONFIG": reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG"),
    "START_ADDR": reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR"),
    "END_ADDR": reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR"),
}
_REGS = ("FILTER_CONFIG", "START_ADDR", "END_ADDR")

_R0 = 0x0220_0000
_SPAN = 0x8000
_PAGE = 0x1000
_WIN_PAGES = (1, 6)
_GRANULE = {1: 0x1000, 0: 8}
_AXLENS = (0, 1, 3, 7)
_SETS = 4
_PROBES = 10
_DRAW_TRIES = 4000
_SET_TRIES = 400
_PIN_TRIES = 64
_WORD = 8
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_PROT_NS = 0b010
# Steps 3 to 5 grade the probes step 2 issued, with no simulation time of their own, so
# their checker lines are fenced after the step 2 stamp and only steps 1, 2 and 6 stamp.
_STEPS = ("S1", "S2", "S6")
_CHECKERS = (
    ("CHK-OFM-RESET", "S1"),
    ("CHK-OFM-LOWEST-WINS", "S2"),
    ("CHK-OFM-DENY-DECERR", "S2"),
    ("CHK-OFM-MATCH-TERMS", "S2"),
    ("CHK-OFM-UNMATCHED-PASS", "S2"),
    ("CHK-OFM-RESTORE", "S6"),
)
_TERMS = ("range", "enabled", "ns", "burst")
_KINDS = (
    ("match", 30),
    ("granule_out", 15),
    ("ns_flip", 12),
    ("burst_b0", 10),
    ("overlap", 20),
    ("random", 8),
)


def _outbound(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


def _seed_word(addr: int) -> int:
    return 0x0F5E_0000_0000_0000 | ((addr & 0xFF_FFFF) << 16) | 0xA5A5


def entry_word(e: dict) -> int:
    return (
        (_READ_ALLOWED if e["read"] else 0)
        | (_WRITE_ALLOWED if e["write"] else 0)
        | (_ENTRY_ENABLED if e["enabled"] else 0)
        | (_ALLOW_NS if e["ns"] else 0)
        | (_ALLOW_BURST if e["burst"] else 0)
    )


def failed_terms(e: dict, p: dict) -> set[str]:
    """The match terms of index.adoc that entry `e` fails for probe `p` (`src_id` 0)."""
    g = _GRANULE[e["burst"]]
    lo, hi = e["start"] & ~(g - 1), e["end"] | (g - 1)
    failed = set()
    if not e["enabled"]:
        failed.add("enabled")
    if not lo <= p["addr"] <= hi:
        failed.add("range")
    if p["ns"] != e["ns"]:
        failed.add("ns")
    if not e["burst"] and p["axlen"]:
        failed.add("burst")
    return failed


def _admits(
    table: list[dict],
    p: dict,
    waive: dict[int, str] | None = None,
    add: dict[int, str] | None = None,
) -> bool:
    """The golden verdict with term `waive[idx]` passing or `add[idx]` failing on one entry."""
    for e in table:
        failed = failed_terms(e, p) - {(waive or {}).get(e["idx"])}
        if (add or {}).get(e["idx"]):
            failed.add(add[e["idx"]])
        if not failed:
            return bool(e["write"] if p["write"] else e["read"])
    return True


def golden(table: list[dict], p: dict) -> dict:
    """Lowest matching entry and its permission bit, or the unmatched pass."""
    matching = [e for e in table if not failed_terms(e, p)]
    out = {"matching": [e["idx"] for e in matching], "entry": None, "allowed": True}
    if matching:
        first = matching[0]
        out["entry"] = first["idx"]
        out["allowed"] = bool(first["write"] if p["write"] else first["read"])
    return out


def _window(rng: random.Random, burst: int) -> tuple[int, int]:
    page = rng.randint(*_WIN_PAGES)
    base = _R0 + page * _PAGE
    if burst:
        count = rng.randint(1, min(2, _WIN_PAGES[1] + 1 - page))
        if count == 2:
            # Two 4 KB granules: the write-back of the widened edges does not fire, so the
            # programmed edges read back as written and the bytes between them and the
            # granule edges are reached only through the widening.
            return base + 8 * rng.randrange(512), base + 2 * _PAGE - 1 - 8 * rng.randrange(512)
        return base, base + _PAGE - 1
    first = rng.randrange(0, 512 - 16)
    return base + 8 * first, base + 8 * (first + rng.randint(1, 16)) - 1


def _widened(e: dict) -> tuple[int, int]:
    g = _GRANULE[e["burst"]]
    return e["start"] & ~(g - 1), e["end"] | (g - 1)


def _overlap(rng: random.Random, low: dict, high: dict) -> None:
    """Place `high`'s window over part of `low`'s widened window."""
    lo, hi = _widened(low)
    if high["burst"]:
        page = (lo - _R0) // _PAGE
        count = rng.randint(1, min(2, _WIN_PAGES[1] + 1 - page))
        high["start"] = _R0 + page * _PAGE
        high["end"] = high["start"] + count * _PAGE - 1
        return
    first = rng.randrange((hi + 1 - lo) // 8)
    page_left = (_PAGE - ((lo + 8 * first) % _PAGE)) // 8
    high["start"] = lo + 8 * first
    high["end"] = high["start"] + 8 * rng.randint(1, min(16, page_left)) - 1


def _axlen(rng: random.Random, addr: int, options: tuple[int, ...]) -> int:
    room = (_PAGE - addr % _PAGE) // 8
    fit = [n for n in options if n + 1 <= room]
    return rng.choice(fit) if fit else 0


def _in(rng: random.Random, lo: int, hi: int) -> int:
    return lo + 8 * rng.randrange((hi + 1 - lo) // 8)


def _probe(rng: random.Random, table: list[dict], pair: tuple[dict, dict]) -> dict:
    kind = rng.choices([k for k, _ in _KINDS], weights=[w for _, w in _KINDS])[0]
    e = rng.choice(table)
    if kind == "burst_b0":
        b0 = [x for x in table if not x["burst"]]
        e = rng.choice(b0) if b0 else e
    if kind == "overlap":
        e = pair[0]
    ns = e["ns"]
    if kind == "random":
        addr = _R0 + 8 * rng.randrange(_SPAN // 8)
        ns = rng.randint(0, 1)
    elif kind == "granule_out":
        g = _GRANULE[e["burst"]]
        lo, hi = _widened(e)
        addr = lo - g + 8 * rng.randrange(g // 8) if rng.randint(0, 1) else _in(rng, hi + 1, hi + g)
    elif kind == "overlap":
        (llo, lhi), (hlo, hhi) = _widened(pair[0]), _widened(pair[1])
        lo, hi = max(llo, hlo), min(lhi, hhi)
        addr = _in(rng, lo, hi) if hi > lo else _in(rng, llo, lhi)
    else:
        addr = _in(rng, *_widened(e))
    if kind == "ns_flip":
        ns ^= 1
    both_burst = kind != "overlap" or (pair[0]["burst"] and pair[1]["burst"])
    if kind == "burst_b0":
        axlen = _axlen(rng, addr, _AXLENS[1:])
    elif kind == "random" or (e["burst"] and both_burst):
        axlen = _axlen(rng, addr, _AXLENS)
    else:
        axlen = 0
    return {"kind": kind, "addr": addr, "ns": ns, "axlen": axlen, "write": rng.randint(0, 1)}


def _table(rng: random.Random) -> tuple[list[dict], tuple[dict, dict]]:
    count = rng.randint(2, 6)
    table = []
    for idx in sorted(rng.sample(range(16), count)):
        burst = rng.randint(0, 1)
        start, end = _window(rng, burst)
        table.append(
            {
                "idx": idx,
                "enabled": int(rng.random() < 0.8),
                "ns": rng.randint(0, 1),
                "burst": burst,
                "read": rng.randint(0, 1),
                "write": rng.randint(0, 1),
                "start": start,
                "end": end,
            }
        )
    low, high = sorted(rng.sample(range(count), 2))
    _overlap(rng, table[low], table[high])
    return table, (table[low], table[high])


def classify(table: list[dict], p: dict) -> dict:
    """The graded cells of probe `p`. A term cell counts only where the response turns on the
    term: treating it as passing on that entry changes the golden verdict, which also makes that
    entry the lowest matching one."""
    gold = golden(table, p)
    fails = {e["idx"]: failed_terms(e, p) for e in table}
    cells = set()

    def turns(**kw) -> bool:
        return _admits(table, p, **kw) != gold["allowed"]

    if gold["entry"] is None:
        cells.add("unmatched")
    if len(gold["matching"]) > 1:
        cells.add("multi_wr" if p["write"] else "multi_rd")
        others = [e for e in table if e["idx"] in gold["matching"][1:]]
        bits = [bool(e["write"] if p["write"] else e["read"]) for e in others]
        if not gold["allowed"] and any(bits):
            cells.add("lowest_key")
        if gold["allowed"] and not all(bits):
            cells.add("lowest_admit")
    for e in table:
        f = fails[e["idx"]]
        if len(f) == 1 and turns(waive={e["idx"]: next(iter(f))}):
            cells.add(f"term_{next(iter(f))}")
            if f == {"burst"} and p["axlen"] == 1:
                cells.add("burst2_b0")
        if (
            "range" not in f
            and not e["start"] <= p["addr"] <= e["end"]
            and turns(add={e["idx"]: "range"})
        ):
            cells.add("widened")
    cells.add("passed" if gold["allowed"] else "denied")
    return {"gold": gold, "fails": fails, "cells": cells}


REQUIRED_CELLS = (
    {"unmatched", "multi_rd", "multi_wr", "lowest_key", "lowest_admit", "passed", "denied"}
    | {"lowest_other_dir"}
    | {"widened", "burst2_b0"}
    | {f"term_{t}" for t in _TERMS}
)


def _free(lo: int, hi: int, covers: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of [lo, hi] that no range of `covers` holds (all edges on 8-byte words)."""
    out = [(lo, hi)]
    for clo, chi in covers:
        out = [
            part
            for a, b in out
            for part in (((a, b),) if chi < a or clo > b else ((a, clo - 1), (chi + 1, b)))
            if part[0] <= part[1]
        ]
    return out


def range_windows(table: list[dict]) -> dict[int, list[list[tuple[int, int]]]]:
    """Per enabled entry with the bit of a direction clear, the free parts of the granule below
    and of the granule above its widened window (a side with none left out): a probe there with
    AxPROT[1] equal to the entry's `allow_ns` and AxLEN 0 matches no entry and passes, and with
    the entry's range term passing it would match that entry and be denied."""
    out = {}
    for e in table:
        if not e["enabled"] or (e["read"] and e["write"]):
            continue
        covers = [_widened(x) for x in table if x["enabled"] and x["ns"] == e["ns"]]
        g = _GRANULE[e["burst"]]
        lo, hi = _widened(e)
        sides = [
            _free(a, b, covers)
            for a, b in ((lo - g, lo - 1), (hi + 1, hi + g))
            if _R0 <= a and b < _R0 + _SPAN
        ]
        sides = [s for s in sides if s]
        if sides:
            out[e["idx"]] = sides
    return out


def _range_pins(rng: random.Random, table: list[dict]) -> list[dict] | None:
    """One probe per window of `range_windows`, at a drawn side and word, in the direction whose
    bit the entry clears; None when one of them does not classify as the range-term probe."""
    pins = []
    windows = range_windows(table)
    for e in table:
        sides = windows.get(e["idx"])
        if sides is None:
            continue
        parts = rng.choice(sides)
        k = rng.randrange(sum((b + 1 - a) // 8 for a, b in parts))
        for a, b in parts:
            if k < (b + 1 - a) // 8:
                addr = a + 8 * k
                break
            k -= (b + 1 - a) // 8
        dirs = [w for w, bit in ((0, e["read"]), (1, e["write"])) if not bit]
        p = {
            "kind": "pin_range",
            "target": e["idx"],
            "addr": addr,
            "ns": e["ns"],
            "axlen": 0,
            "write": rng.choice(dirs),
        }
        p.update(classify(table, p))
        if not _range_pin_ok(p):
            return None
        pins.append(p)
    return pins


def _range_pin_ok(p: dict) -> bool:
    return (
        p["gold"]["entry"] is None
        and p["fails"][p["target"]] == {"range"}
        and "term_range" in p["cells"]
    )


def _in_span(p: dict) -> bool:
    last = p["addr"] + 8 * (p["axlen"] + 1) - 1
    return _R0 <= p["addr"] and last < _R0 + _SPAN and p["addr"] // _PAGE == last // _PAGE


def _pin(rng: random.Random, table: list[dict]) -> dict | None:
    """A 2-beat probe against an enabled `allow_burst` 0 entry that fails only that term there,
    the response turning on it; None when the table holds no such entry and address."""
    for e in rng.sample(table, len(table)):
        if not e["enabled"] or e["burst"]:
            continue
        for write in rng.sample((0, 1), 2):
            for _ in range(_PIN_TRIES):
                p = {
                    "kind": "pin_burst2",
                    "addr": _in(rng, *_widened(e)),
                    "ns": e["ns"],
                    "axlen": 1,
                    "write": write,
                }
                if not _in_span(p):
                    continue
                p.update(classify(table, p))
                if "burst2_b0" in p["cells"] and p["fails"][e["idx"]] == {"burst"}:
                    return p
    return None


def _set(rng: random.Random) -> tuple[list[dict], tuple[dict, dict], list[dict]]:
    """One rule table that holds the pinned 2-beat probe and a pinned outside-granule probe per
    window of `range_windows`, redrawn until it does."""
    for _ in range(_SET_TRIES):
        table, pair = _table(rng)
        pin = _pin(rng, table)
        ranged = _range_pins(rng, table) if pin is not None else None
        if ranged is not None:
            return table, pair, [pin, *ranged]
    raise AssertionError(f"no rule table held the pinned probes in {_SET_TRIES} tries")


def _twin_ok(key: dict, twin: dict) -> bool:
    """`twin` is the `lowest_key` probe `key` in the other direction, decided by the same
    lowest matching entry."""
    return (
        "lowest_key" in key["cells"]
        and twin["write"] != key["write"]
        and all(twin[f] == key[f] for f in ("addr", "ns", "axlen"))
        and twin["gold"]["entry"] == key["gold"]["entry"]
        and len(twin["gold"]["matching"]) >= 2
    )


def _own_bit(table: list[dict], p: dict) -> int:
    """The bit for `p`'s direction of the lowest matching entry."""
    e = next(x for x in table if x["idx"] == p["gold"]["entry"])
    return e["write"] if p["write"] else e["read"]


def _other_dir(rng: random.Random, table: list[dict], probes: list[dict]) -> dict | None:
    """A pinned twin of one `lowest_key` probe of the set: the same address, AxPROT[1] and AxLEN
    in the other direction, decided by its own bit of the same lowest entry; a probe whose
    lowest entry sets the other direction's bit is preferred, so the twin passes where the probe
    is denied. None when the set holds no `lowest_key` probe."""
    keys = [p for p in probes if "lowest_key" in p["cells"]]
    if not keys:
        return None
    flip = [k for k in keys if _own_bit(table, {**k, "write": k["write"] ^ 1})]
    key = rng.choice(flip or keys)
    twin = {f: key[f] for f in ("addr", "ns", "axlen")}
    twin.update(kind="pin_other_dir", write=key["write"] ^ 1, key=probes.index(key))
    twin.update(classify(table, twin))
    assert _twin_ok(key, twin), f"other-direction twin {twin} of {key}"
    if _own_bit(table, twin):
        twin["cells"].add("lowest_other_dir")
    return twin


def draw(rng: random.Random) -> tuple[list[dict], int]:
    """Draw the four rule sets with their probes until every graded cell occurs."""
    for attempt in range(1, _DRAW_TRIES + 1):
        sets = []
        seen: set[str] = set()
        for _ in range(_SETS):
            table, pair, pins = _set(rng)
            probes = [_probe(rng, table, pair) for _ in range(_PROBES)]
            for p in probes:
                p.update(classify(table, p))
            probes += pins
            twin = _other_dir(rng, table, probes)
            if twin is not None:
                probes.append(twin)
            for p in probes:
                seen |= p["cells"]
            sets.append(
                {"table": table, "pair": (pair[0]["idx"], pair[1]["idx"]), "probes": probes}
            )
        if REQUIRED_CELLS <= seen:
            return sets, attempt
    raise AssertionError(f"no draw covered {sorted(REQUIRED_CELLS)} in {_DRAW_TRIES} tries")


def check_filters(sets: list[dict]) -> None:
    for s in sets:
        table = s["table"]
        assert 2 <= len(table) <= 6, f"entry count {len(table)}"
        for e in table:
            assert 0 <= e["idx"] <= 15, f"entry index {e['idx']}"
            two_pages = e["burst"] and e["end"] // _PAGE - e["start"] // _PAGE == 1
            g = 8 if two_pages else _GRANULE[e["burst"]]
            assert e["start"] % g == 0 and (e["end"] + 1) % g == 0, f"edges of {e}"
            assert _R0 <= e["start"] <= e["end"] < _R0 + _SPAN, f"window of {e}"
        for p in s["probes"]:
            assert _in_span(p), f"probe 0x{p['addr']:x} off the span or across 4 KB"
            assert p["axlen"] in _AXLENS
        pins = [p for p in s["probes"] if p["kind"] == "pin_burst2"]
        assert len(pins) == 1 and "burst2_b0" in pins[0]["cells"], f"pinned probes {pins}"
        windows = sorted(range_windows(table))
        ranged = [p for p in s["probes"] if p["kind"] == "pin_range"]
        targets = sorted(p["target"] for p in ranged)
        assert targets == windows, f"outside-granule pins on {targets}, windows {windows}"
        assert all(_range_pin_ok(p) for p in ranged), f"outside-granule pins {ranged}"
        keys = [
            p for p in s["probes"] if "lowest_key" in p["cells"] and p["kind"] != "pin_other_dir"
        ]
        twins = [p for p in s["probes"] if p["kind"] == "pin_other_dir"]
        assert len(twins) == (1 if keys else 0), f"{len(twins)} other-direction twins, {len(keys)}"
        for p in twins:
            assert _twin_ok(s["probes"][p["key"]], p), f"other-direction twin {p}"
            assert ("lowest_other_dir" in p["cells"]) == bool(_own_bit(table, p)), f"twin {p}"
    assert any("lowest_other_dir" in p["cells"] for s in sets for p in s["probes"])


def _table_text(table: list[dict]) -> str:
    return ";".join(
        f"E{e['idx']}[en{e['enabled']} ns{e['ns']} b{e['burst']} r{e['read']} w{e['write']} "
        f"0x{e['start']:x}..0x{e['end']:x}]"
        for e in table
    )


class smc_outfilt_rule_matrix_rand_test_seq(SmcCsrSeq):
    """Program four drawn outbound rule tables and grade their JTAG probes against them."""

    def __init__(self, name: str = "smc_outfilt_rule_matrix_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.jtag_accesses = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._shadow: dict[int, int] = {}
        self._results: list[dict] = []
        self._programmed: set[int] = set()
        self._beats = {"awvalid": 0, "wvalid": 0, "arvalid": 0}
        self._events: list[tuple[str, int, int, int]] = []
        self._wdata_no = 0
        self.total = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _watch_output(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for name in self._beats:
                sig = getattr(top, f"tb_output_axi_{name}")
                assert sig.value.is_resolvable, f"tb_output_axi_{name} is X/Z ({sig.value})"
                self._beats[name] += int(sig.value)
            for kind in ("aw", "ar"):
                vals = []
                for name in (f"{kind}valid", f"{kind}ready", f"{kind}prot", f"{kind}len"):
                    sig = getattr(ifc, name)
                    assert sig.value.is_resolvable, f"u_output_axi_if.{name} is X/Z ({sig.value})"
                    vals.append(int(sig.value))
                tb_addr = getattr(top, f"tb_output_axi_{kind}addr")
                assert tb_addr.value.is_resolvable, f"tb_output_axi_{kind}addr is X/Z"
                if vals[0] and vals[1]:
                    self._events.append((kind, int(tb_addr.value), vals[2], vals[3]))

    async def _program(self, e: dict) -> None:
        idx, word = e["idx"], entry_word(e)
        await self.csr_write(f"OB{idx}_OFF", _outbound("FILTER_CONFIG", idx), 0, _WORD)
        await self.csr_write(f"OB{idx}_START", _outbound("START_ADDR", idx), e["start"], _WORD)
        await self.csr_write(f"OB{idx}_END", _outbound("END_ADDR", idx), e["end"], _WORD)
        await self.csr_write(f"OB{idx}_CFG", _outbound("FILTER_CONFIG", idx), word, _WORD)
        for reg, want in (
            ("FILTER_CONFIG", word | _RESET["FILTER_CONFIG"]),
            ("START_ADDR", e["start"]),
            ("END_ADDR", e["end"]),
        ):
            await self.csr_read(f"OB{idx}_{reg}_RB", _outbound(reg, idx), want, _WORD)
        self._programmed.add(idx)

    async def _restore(self, idx: int, tag: str) -> list[int]:
        for reg in _REGS:
            await self.csr_write(f"{tag}_OB{idx}_{reg}", _outbound(reg, idx), _RESET[reg], _WORD)
        return [
            await self.csr_read(f"{tag}_OB{idx}_{reg}_RB", _outbound(reg, idx), _RESET[reg], _WORD)
            for reg in _REGS
        ]

    async def _hold(self, writes0: int, reads0: int, tag: str) -> None:
        top = cocotb.top
        for cycle in range(1, BLOCKED_WRITE_HOLD_CYCLES + 1):
            await ClockCycles(top.clk_smc_i, 1)
            got = output_responder_counts()
            assert got == (writes0, reads0), (
                f"{tag}: SYS_OUT counters moved to {got} from {(writes0, reads0)} {cycle} "
                f"clk_smc_i after a denied request"
            )

    @staticmethod
    def _cell(p: dict) -> str:
        return (
            f"{'wr' if p['write'] else 'rd'} 0x{p['addr']:x} AxLEN {p['axlen']} AxPROT[1] {p['ns']}"
        )

    async def _run_probe(self, set_no: int, n: int, p: dict) -> None:
        tag = f"T{set_no}P{n}"
        responder = self.cfg.sys_out_mem
        beats = [p["addr"] + 8 * b for b in range(p["axlen"] + 1)]
        for b in beats:
            assert responder.read_int(b, _WORD) == self._shadow[b], f"{tag}: seed at 0x{b:x}"
        prot = _PROT_NS if p["ns"] else 0
        passed = p["gold"]["allowed"]
        words = []
        if p["write"]:
            for b in beats:
                self._wdata_no += 1
                words.append(0xC0DE_0000_0000_0000 | (self._wdata_no << 32) | (b & 0xFFFF_FFFF))
        writes0, reads0 = output_responder_counts()
        beats0, events0 = dict(self._beats), len(self._events)
        item = SmcSysAxiItem(f"jtag_{tag}")
        item.op = SmcSysAxiOp.WRITE if p["write"] else SmcSysAxiOp.READ
        item.addr, item.length, item.beats, item.prot = p["addr"], _WORD, len(beats), prot
        item.wdata = sum(w << (64 * i) for i, w in enumerate(words))
        item.timeout_ns = _AXI_BOUND_NS
        if not passed:
            item.allow_error = item.expect_error = True
            item.expected_resp = RESP_DECERR
        await _OneShot(item, f"jtag_{tag}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        assert not item.timed_out, f"{tag}: JTAG access expired after {_AXI_BOUND_NS} ns"
        want = RESP_OKAY if passed else RESP_DECERR
        assert item.resp_code == want, (
            f"{tag}: resp {item.resp_code}, golden {want} (matching {p['gold']['matching']}, "
            f"lowest {p['gold']['entry']}) for {self._cell(p)}"
        )
        kind = "aw" if p["write"] else "ar"
        if not passed:
            await self._hold(writes0, reads0, tag)
            seen = {k: self._beats[k] - beats0[k] for k in self._beats}
            assert seen == {"awvalid": 0, "wvalid": 0, "arvalid": 0}, f"{tag}: valids {seen}"
            assert not self._events[events0:], f"{tag}: handshakes {self._events[events0:]}"
            for b in beats:
                held = responder.read_int(b, _WORD)
                assert held == self._shadow[b], f"{tag}: denied request changed 0x{b:x}"
            text = f"DECERR, seed kept, no valid, counters held {BLOCKED_WRITE_HOLD_CYCLES} cycles"
        else:
            await check_output_responder_delta(
                start_writes=writes0,
                start_reads=reads0,
                write_delta=int(bool(p["write"])),
                read_delta=int(not p["write"]),
                last_addr=p["addr"],
                last_wdata=words[-1] if p["write"] else None,
            )
            writes1, reads1 = output_responder_counts()
            delta = (writes1 - writes0, reads1 - reads0)
            assert delta == ((1, 0) if p["write"] else (0, 1)), f"{tag}: counter deltas {delta}"
            events = [e for e in self._events[events0:] if e[0] == kind]
            assert events == [(kind, p["addr"], prot, p["axlen"])], (
                f"{tag}: {kind} handshakes {events}, want one at 0x{p['addr']:x} prot {prot} "
                f"len {p['axlen']}"
            )
            if p["write"]:
                for i, b in enumerate(beats):
                    got = responder.read_int(b, _WORD)
                    assert got == words[i], f"{tag}: beat {i} left 0x{got:x} at 0x{b:x}"
                    self._shadow[b] = words[i]
            else:
                exp = sum(self._shadow[b] << (64 * i) for i, b in enumerate(beats))
                assert item.rdata == exp, f"{tag}: rdata 0x{item.rdata:x}, want 0x{exp:x}"
            text = (
                f"OKAY, one {kind} handshake at 0x{p['addr']:x} prot {prot} len {p['axlen']}, "
                f"counter +1, {'landed' if p['write'] else 'returned'}"
            )
        self._results.append({"tag": tag, "p": p, "resp": item.resp_code, "text": text})
        cocotb.log.info(
            "PROBE %s: %s golden entry %s matching %s -> %s",
            tag,
            self._cell(p),
            p["gold"]["entry"],
            p["gold"]["matching"],
            text,
        )

    def _with(self, cell: str) -> list[dict]:
        return [r for r in self._results if cell in r["p"]["cells"]]

    def _list(self, recs: list[dict]) -> str:
        return ", ".join(
            f"{r['tag']}({self._cell(r['p'])}: entry {r['p']['gold']['entry']} "
            f"matching {r['p']['gold']['matching']} resp {r['resp']})"
            for r in recs
        )

    async def body(self) -> None:
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        top = cocotb.top
        edges = [0]

        async def _count() -> None:
            while True:
                await RisingEdge(top.clk_smc_i)
                edges[0] += 1

        counter = cocotb.start_soon(_count())
        await self.wait_fuse_sense_done(max_cycles=_FUSE_BOUND)
        counter.kill()
        fuse = []
        for sig in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n):
            assert sig.value.is_resolvable, f"{sig._name} is X/Z after the fuse-sense wait"
            fuse.append(int(sig.value))
        watcher = cocotb.start_soon(self._watch_output())

        # S1: draw, reset words beside the RDL (control), preset every seed word.
        sets, attempts = draw(self.rng)
        check_filters(sets)
        self.total = sum(len(s["probes"]) for s in sets)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d rule sets x %d drawn probes plus %d pinned "
            "(attempt %d): %s",
            self.seed,
            _SETS,
            _PROBES,
            self.total - _SETS * _PROBES,
            attempts,
            " | ".join(
                f"set{i} overlap E{s['pair'][0]}/E{s['pair'][1]} {_table_text(s['table'])} "
                f"probes " + ";".join(f"{p['kind']} {self._cell(p)}" for p in s["probes"])
                for i, s in enumerate(sets)
            ),
        )
        reset_reads = []
        for idx in range(16):
            words = [
                await self.csr_read(f"OB{idx}_{r}_AT_START", _outbound(r, idx), length=_WORD)
                for r in _REGS
            ]
            assert not words[0] & _ENTRY_ENABLED, f"outbound entry {idx} enabled at start"
            reset_reads.append(f"E{idx} " + " ".join(f"{r}=0x{w:x}" for r, w in zip(_REGS, words)))
            assert words == [_RESET[r] for r in _REGS], (
                f"outbound entry {idx} before any write reads {reset_reads[-1]}, "
                f"filter_ctrl.rdl reset words {[hex(_RESET[r]) for r in _REGS]}"
            )
        for s in sets:
            for p in s["probes"]:
                for b in range(p["axlen"] + 1):
                    addr = p["addr"] + 8 * b
                    self._shadow.setdefault(addr, _seed_word(addr))
        for addr, word in self._shadow.items():
            responder.write_int(addr, word, _WORD)
        self._mark_step("S1")
        self._log_chk(
            "CHK-OFM-RESET",
            "outbound entries 0 to 15 before any write equal the RDL reset words: "
            f"{'; '.join(reset_reads)}; RDL reset words "
            f"FILTER_CONFIG=0x{_RESET['FILTER_CONFIG']:x} START_ADDR=0x{_RESET['START_ADDR']:x} "
            f"END_ADDR=0x{_RESET['END_ADDR']:x}; {len(self._shadow)} seed words preset",
        )

        # S2: per rule set program, read back and run its probes against the golden.
        for set_no, s in enumerate(sets):
            for e in s["table"]:
                await self._program(e)
            for n, p in enumerate(s["probes"]):
                await self._run_probe(set_no, n, p)
            for e in s["table"]:
                await self._restore(e["idx"], f"T{set_no}")
        self._mark_step("S2")

        # Step 3, on the step 2 probes: the lowest matching entry decides; denials are
        # DECERR with no SYS_OUT beat.
        multi = self._with("multi_rd") + self._with("multi_wr")
        key = self._with("lowest_key")
        admit = self._with("lowest_admit")
        denied = self._with("denied")
        assert key and admit and self._with("multi_rd") and self._with("multi_wr") and denied
        assert all(r["resp"] == RESP_DECERR for r in denied)
        by_tag = {r["tag"]: r for r in self._results}
        pairs = []
        for r in [r for r in self._results if r["p"]["kind"] == "pin_other_dir"]:
            set_no = int(r["tag"][1:].split("P")[0])
            k = by_tag[f"T{set_no}P{r['p']['key']}"]
            e = next(x for x in sets[set_no]["table"] if x["idx"] == r["p"]["gold"]["entry"])
            bit = e["write"] if r["p"]["write"] else e["read"]
            assert _twin_ok(k["p"], r["p"]), f"{r['tag']} is no twin of {k['tag']}"
            assert k["resp"] == RESP_DECERR and r["resp"] == (RESP_OKAY if bit else RESP_DECERR), (
                f"{k['tag']} resp {k['resp']} and its twin {r['tag']} resp {r['resp']} on "
                f"lowest entry E{e['idx']} (read_allowed {e['read']} write_allowed {e['write']})"
            )
            pairs.append(f"{k['tag']}/{r['tag']} E{e['idx']} bit {bit}")
        twins = sum(1 for s in sets for p in s["probes"] if p["kind"] == "pin_other_dir")
        assert pairs and len(pairs) == twins, f"{len(pairs)} other-direction pairs, want {twins}"
        assert any(p.endswith("bit 1") for p in pairs), f"no pair with the bit set: {pairs}"
        self._log_chk(
            "CHK-OFM-LOWEST-WINS",
            f"drawn=overlaps {[s['pair'] for s in sets]}; {len(multi)} probes matched two or more "
            f"entries and answered by the lowest one's bit for their direction; {len(key)} of "
            f"them denied by the lowest entry although a higher matching entry permits and "
            f"{len(admit)} passed by the lowest entry although a higher matching entry denies; "
            f"pinned other-direction pairs, the denied probe and its twin in the other direction "
            f"answered by the same lowest entry's own bit for it ({len(pairs)}, "
            f"{sum(p.endswith('bit 1') for p in pairs)} with that bit set): {'; '.join(pairs)}; "
            f"{self._list(multi)}",
        )
        self._log_chk(
            "CHK-OFM-DENY-DECERR",
            f"drawn={len(denied)} denied probes; each answered DECERR within the guard, kept its "
            f"seed words, raised no SYS_OUT valid or handshake and moved neither counter for "
            f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i: {self._list(denied)}",
        )

        # Step 4, on the step 2 probes: probes failing allow_ns, allow_burst, the granule
        # range or entry_enabled.
        terms = {t: self._with(f"term_{t}") for t in _TERMS}
        pinned = [r for r in self._results if r["p"]["kind"] == "pin_burst2"]
        widened = self._with("widened")
        assert all(terms.values()) and widened
        assert len({r["tag"].split("P")[0] for r in pinned}) == _SETS == len(pinned)
        ranged = [r for r in self._results if r["p"]["kind"] == "pin_range"]
        per_set = [len(range_windows(s["table"])) for s in sets]
        assert len(ranged) == sum(per_set), f"{len(ranged)} outside-granule pins, want {per_set}"
        assert all(_range_pin_ok(r["p"]) and r["resp"] == RESP_OKAY for r in ranged)
        graded = sorted(
            {id(r): r for v in terms.values() for r in v}.values(), key=lambda r: r["tag"]
        )
        self._log_chk(
            "CHK-OFM-MATCH-TERMS",
            "drawn="
            + ",".join(f"{t}:{len(v)}" for t, v in terms.items())
            + "; every probe whose response turns on one term of one entry fell through to the "
            f"next matching entry's bit or passed as the golden states: {self._list(graded)}; "
            f"pinned 2-beat bursts against allow_burst 0, one per set: {self._list(pinned)}; "
            f"pinned probes one granule outside each enabled window whose entry clears the bit "
            f"of the probe's direction, matching no entry, one per such window ({per_set} per "
            f"set, {len(ranged)} in all): {self._list(ranged)}; probes decided inside a widened "
            f"granule outside the programmed edges: {self._list(widened)}",
        )

        # Step 5, on the step 2 probes: unmatched traffic passes.
        unmatched = self._with("unmatched")
        passed = self._with("passed")
        assert unmatched and all(r["resp"] == RESP_OKAY for r in unmatched)
        self._log_chk(
            "CHK-OFM-UNMATCHED-PASS",
            f"drawn={sorted({r['p']['kind'] for r in unmatched})}; {len(unmatched)} probes "
            f"matched no enabled entry and answered OKAY with one handshake at the driven address "
            f"and AxPROT and the counter up by one within {RESPONDER_OBS_TIMEOUT_CYCLES} "
            f"clk_smc_i ({len(passed)} passed probes in all): {self._list(unmatched)}",
        )

        # S6: entries back at their reset words.
        final = []
        for idx in sorted(self._programmed):
            got = await self._restore(idx, "FINAL")
            final.append(f"E{idx}=" + "/".join(f"0x{w:x}" for w in got))
        watcher.kill()
        self._mark_step("S6")
        self._log_chk(
            "CHK-OFM-RESTORE",
            f"every programmed outbound entry reads its reset words: {' '.join(final)}",
        )
        self._finish(fuse, edges[0])

    def _finish(self, fuse: list[int], edges: int) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: fuse-sense wait bound %d clk_smc_i (returned after %d, "
            "tb_fuse_sense_done %d tb_fuse_reset_n %d tb_rst_warm_smc_clk_n %d); every SEP_IN "
            "access under the driver guard of %d ns (%d accesses); every JTAG access under %d ns "
            "(%d accesses); denial hold %d clk_smc_i; responder poll %d clk_smc_i; expiry "
            "raises AssertionError",
            _FUSE_BOUND,
            edges,
            *fuse,
            self.cfg.axi_timeout_ns,
            self.accesses,
            _AXI_BOUND_NS,
            self.jtag_accesses,
            BLOCKED_WRITE_HOLD_CYCLES,
            RESPONDER_OBS_TIMEOUT_CYCLES,
        )
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        total = self.total
        assert self.jtag_accesses == total, f"{self.jtag_accesses} JTAG probes, want {total}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; %d JTAG probes (exactly the %d "
            "drawn and pinned); %d SEP_IN accesses; stamps %s",
            "<".join(_STEPS),
            ",".join(c for c, _ in self._chk_marks),
            self.jtag_accesses,
            total,
            self.accesses,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
