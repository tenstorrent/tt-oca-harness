# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded inbound filter rule tables against SYS_IN probes with drawn attributes.

Spec sources: axi_filter index.adoc (Match, Then Permit; Address Range Granule; Blocked
Transactions), filter_ctrl.rdl FILTER_CONFIG, START_ADDR and END_ADDR, fabric.adoc (Inbound
Filtering; the filter figure, whose asset names AxUSER[3:0] as src_id).

Four rule tables of 2 to 6 inbound entries (indices 2 to 15) are drawn from the seed, each with
12 drawn SYS_IN probes and the pinned no-match probes: one granule outside each enabled window
with a permission bit set whose outside granule matches no entry, inside a disabled window,
AxPROT[1] failing and AxLEN failing.
The golden of every probe comes from the drawn table alone: the entries whose match terms all
hold, the lowest-numbered one and its permission bit for the channel, or the block when none
matches. Every probe word lives in the SPM span at its base plus 0x4_0000.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, _field_mask, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_READ_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_WRITE_ALLOWED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_ENTRY_ENABLED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_ALLOW_NS = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_ALLOW_BURST = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_SRC_ID = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm")
_SRC_SHIFT = (_SRC_ID & -_SRC_ID).bit_length() - 1
_RESET = {
    "FILTER_CONFIG": reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG"),
    "START_ADDR": reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR"),
    "END_ADDR": reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR"),
}
_REGS = ("FILTER_CONFIG", "START_ADDR", "END_ADDR")

_P0 = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x4_0000
_SPAN = 0x8000
_PAGE = 0x1000
_WIN_PAGES = (1, 6)
_GRANULE = {1: 0x1000, 0: 8}
_AXLENS = (0, 1, 3, 7, 15)
_SETS = 4
_PROBES = 12
_TOTAL = _SETS * _PROBES
_DRAW_TRIES = 4000
_SET_TRIES = 400
_PIN_TRIES = 64
_DECERR = 3
_OKAY = 0
_AXI_BOUND_NS = 50_000
_FUSE_BOUND = 200_000
_PROT_NS = 0b010
# Steps 3 to 6 grade the probes step 2 issued, with no simulation time of their own, so
# their checker lines are fenced after the step 2 stamp and only steps 1, 2 and 7 stamp.
_STEPS = ("S1", "S2", "S7")
_CHECKERS = (
    ("CHK-IFM-RESET", "S1"),
    ("CHK-IFM-NO-MATCH-BLOCK", "S2"),
    ("CHK-IFM-LOWEST-WINS", "S2"),
    ("CHK-IFM-SRC-ID", "S2"),
    ("CHK-IFM-MATCH-TERMS", "S2"),
    ("CHK-IFM-RESTORE", "S7"),
)
_TERMS = ("range", "enabled", "ns", "burst")
_KINDS = (
    ("match", 30),
    ("granule_out", 14),
    ("ns_flip", 10),
    ("burst_b0", 9),
    ("user_wrong", 10),
    ("overlap", 17),
    ("random", 10),
)
# Pinned no-match probe kinds: the term that alone fails on the entry the probe is aimed at,
# and the cell that makes the response depend on that term.
_PINS = {
    "pin_range": ("range", "nomatch_range"),
    "pin_disabled": ("enabled", "nomatch_disabled"),
    "pin_ns": ("ns", "nomatch_ns_all"),
    "pin_len": ("burst", "nomatch_len_all"),
}


def _reg(reg: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_INBOUND_FILTER_CTRL_{reg}_BASE_ADDR", entry)


def _seed_word(addr: int) -> int:
    return 0x1F00_0000_0000_0000 | ((addr & 0xF_FFFF) << 24) | 0x5A_5A5A


def entry_word(e: dict) -> int:
    word = (
        (_READ_ALLOWED if e["read"] else 0)
        | (_WRITE_ALLOWED if e["write"] else 0)
        | (_ENTRY_ENABLED if e["enabled"] else 0)
        | (_ALLOW_NS if e["ns"] else 0)
        | (_ALLOW_BURST if e["burst"] else 0)
        | (e["src"] << _SRC_SHIFT)
    )
    assert word & _SRC_ID == e["src"] << _SRC_SHIFT
    return word


def failed_terms(e: dict, p: dict) -> set[str]:
    """The match terms of index.adoc that entry `e` fails for probe `p`."""
    g = _GRANULE[e["burst"]]
    lo, hi = e["start"] & ~(g - 1), e["end"] | (g - 1)
    failed = set()
    if not e["enabled"]:
        failed.add("enabled")
    if not lo <= p["addr"] <= hi:
        failed.add("range")
    if p["ns"] != e["ns"]:
        failed.add("ns")
    if e["src"] and (p["user"] & 0xF) != e["src"]:
        failed.add("src")
    if not e["burst"] and p["axlen"]:
        failed.add("burst")
    return failed


def golden(table: list[dict], p: dict) -> dict:
    """Lowest matching entry and its permission bit, or the block when none matches."""
    matching = [e for e in table if not failed_terms(e, p)]
    out = {"matching": [e["idx"] for e in matching], "entry": None, "allowed": False}
    if matching:
        first = matching[0]
        out["entry"] = first["idx"]
        out["allowed"] = bool(first["write"] if p["write"] else first["read"])
    return out


def _admits(
    table: list[dict],
    p: dict,
    waive: dict[int, str] | None = None,
    add: dict[int, str] | None = None,
    ignore: str | None = None,
) -> bool:
    """The golden verdict with term `waive[idx]` passing or `add[idx]` failing on one entry,
    or term `ignore` passing on every entry."""
    for e in table:
        failed = failed_terms(e, p) - {ignore, (waive or {}).get(e["idx"])}
        if (add or {}).get(e["idx"]):
            failed.add(add[e["idx"]])
        if not failed:
            return bool(e["write"] if p["write"] else e["read"])
    return False


def _window(rng: random.Random, burst: int) -> tuple[int, int]:
    page = rng.randint(*_WIN_PAGES)
    base = _P0 + page * _PAGE
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


def _overlap(rng: random.Random, low: dict, high: dict) -> None:
    """Place `high`'s window over part of `low`'s widened window."""
    g = _GRANULE[low["burst"]]
    lo, hi = low["start"] & ~(g - 1), low["end"] | (g - 1)
    if high["burst"]:
        page = (lo - _P0) // _PAGE
        count = rng.randint(1, min(2, _WIN_PAGES[1] + 1 - page))
        high["start"] = _P0 + page * _PAGE
        high["end"] = high["start"] + count * _PAGE - 1
        return
    words = (hi + 1 - lo) // 8
    first = rng.randrange(words)
    page_left = (_PAGE - ((lo + 8 * first) % _PAGE)) // 8
    high["start"] = lo + 8 * first
    high["end"] = high["start"] + 8 * rng.randint(1, min(16, page_left)) - 1


def _axlen(rng: random.Random, addr: int, options: tuple[int, ...]) -> int:
    room = (_PAGE - addr % _PAGE) // 8
    fit = [n for n in options if n + 1 <= room]
    return rng.choice(fit) if fit else 0


def _in_window(rng: random.Random, e: dict) -> int:
    g = _GRANULE[e["burst"]]
    lo, hi = e["start"] & ~(g - 1), e["end"] | (g - 1)
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
    user = e["src"] if e["src"] else rng.randrange(16)
    if kind == "overlap" and not e["src"] and pair[1]["src"]:
        user = pair[1]["src"]
    if kind == "random":
        addr = _P0 + 8 * rng.randrange(_SPAN // 8)
        ns = rng.randint(0, 1)
        user = rng.randrange(16)
    elif kind == "granule_out":
        g = _GRANULE[e["burst"]]
        lo, hi = e["start"] & ~(g - 1), e["end"] | (g - 1)
        if rng.randint(0, 1):
            addr = lo - g + 8 * rng.randrange(g // 8)
        else:
            addr = hi + 1 + 8 * rng.randrange(g // 8)
    elif kind == "overlap":
        low, high = pair
        gl, gh = _GRANULE[low["burst"]], _GRANULE[high["burst"]]
        lo = max(low["start"] & ~(gl - 1), high["start"] & ~(gh - 1))
        hi = min(low["end"] | (gl - 1), high["end"] | (gh - 1))
        addr = lo + 8 * rng.randrange((hi + 1 - lo) // 8) if hi > lo else _in_window(rng, low)
    else:
        addr = _in_window(rng, e)
    if kind == "ns_flip":
        ns ^= 1
    if kind == "user_wrong":
        user = rng.choice([u for u in range(16) if u != (e["src"] or 0x10)])
    both_burst = kind != "overlap" or (pair[0]["burst"] and pair[1]["burst"])
    if kind == "burst_b0":
        axlen = _axlen(rng, addr, _AXLENS[1:])
    elif kind == "random" or (e["burst"] and both_burst):
        axlen = _axlen(rng, addr, _AXLENS)
    else:
        axlen = 0
    return {
        "kind": kind,
        "addr": addr,
        "ns": ns,
        "user": user,
        "axlen": axlen,
        "write": rng.randint(0, 1),
    }


def _table(rng: random.Random) -> tuple[list[dict], tuple[dict, dict]]:
    count = rng.randint(2, 6)
    table = []
    for idx in sorted(rng.sample(range(2, 16), count)):
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
                "src": 0 if rng.randint(0, 1) else rng.randint(1, 15),
                "start": start,
                "end": end,
            }
        )
    low, high = sorted(rng.sample(range(count), 2))
    _overlap(rng, table[low], table[high])
    return table, (table[low], table[high])


def classify(table: list[dict], p: dict) -> dict:
    """The graded cells of probe `p`. A term cell counts only where the response turns on the
    term: treating it as passing (or, for an equal `src_id`, as failing) on that entry changes
    the golden verdict, which also makes that entry the lowest matching one."""
    gold = golden(table, p)
    fails = {e["idx"]: failed_terms(e, p) for e in table}
    admit = gold["entry"] is not None and gold["allowed"]
    cells = set()

    def turns(**kw) -> bool:
        return _admits(table, p, **kw) != admit

    if gold["entry"] is None:
        cells.add("nomatch")
        for e in table:
            if fails[e["idx"]] == {"range"} and turns(waive={e["idx"]: "range"}):
                cells.add("nomatch_range")
            if fails[e["idx"]] == {"enabled"} and turns(waive={e["idx"]: "enabled"}):
                cells.add("nomatch_disabled")
        covering = [fails[e["idx"]] for e in table if "range" not in fails[e["idx"]]]
        if turns(ignore="ns") and all("ns" in f for f in covering):
            cells.add("nomatch_ns_all")
        if turns(ignore="burst") and all("burst" in f for f in covering):
            cells.add("nomatch_len_all")
    if len(gold["matching"]) > 1:
        cells.add("multi_wr" if p["write"] else "multi_rd")
        others = [e for e in table if e["idx"] in gold["matching"][1:]]
        bits = [bool(e["write"] if p["write"] else e["read"]) for e in others]
        if not gold["allowed"] and any(bits):
            cells.add("lowest_key")
        if gold["allowed"] and not all(bits):
            cells.add("lowest_admit")
    src_rel = [e for e in table if e["src"] and not (fails[e["idx"]] - {"src"})]
    for e in src_rel:
        if "src" in fails[e["idx"]] and turns(waive={e["idx"]: "src"}):
            cells.add("src_differ")
        if not fails[e["idx"]] and turns(add={e["idx"]: "src"}):
            cells.add("src_equal")
    if gold["entry"] is not None:
        first = next(e for e in table if e["idx"] == gold["entry"])
        if not first["src"] and p["user"] & 0xF and turns(add={first["idx"]: "src"}):
            cells.add("src_wild")
    for e in table:
        f = fails[e["idx"]]
        if len(f) == 1 and turns(waive={e["idx"]: next(iter(f))}):
            cells.add(f"term_{next(iter(f))}")
        if (
            "range" not in f
            and not e["start"] <= p["addr"] <= e["end"]
            and turns(add={e["idx"]: "range"})
        ):
            cells.add("widened")
    if admit:
        cells.add(f"admit_len{p['axlen']}")
        cells.add("admitted")
    else:
        cells.add("blocked")
    return {"gold": gold, "fails": fails, "cells": cells, "src_rel": bool(src_rel)}


REQUIRED_CELLS = (
    {"nomatch", "multi_rd", "multi_wr", "lowest_key", "lowest_admit", "lowest_other_channel"}
    | {"src_equal", "src_differ", "src_wild", "widened"}
    | {cell for _, cell in _PINS.values()}
    | {f"term_{t}" for t in _TERMS}
    | {f"admit_len{n}" for n in _AXLENS}
    | {"admitted", "blocked"}
)


def _in_span(p: dict) -> bool:
    last = p["addr"] + 8 * (p["axlen"] + 1) - 1
    return _P0 <= p["addr"] and last < _P0 + _SPAN and p["addr"] // _PAGE == last // _PAGE


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


def _widened(e: dict) -> tuple[int, int]:
    g = _GRANULE[e["burst"]]
    return e["start"] & ~(g - 1), e["end"] | (g - 1)


def range_windows(table: list[dict]) -> dict[int, list[tuple[int, list[tuple[int, int]]]]]:
    """Per enabled entry with a permission bit set, the (AxUSER[3:0], free parts) options of the
    granule below and of the granule above its widened window: a probe there with AxPROT[1]
    equal to the entry's `allow_ns`, AxLEN 0 and that AxUSER[3:0] matches no entry, and with
    the entry's range term passing it would match that entry and be admitted. An entry with no
    option is left out: its outside granules are matched by other entries."""
    out = {}
    for e in table:
        if not e["enabled"] or not (e["read"] or e["write"]):
            continue
        g = _GRANULE[e["burst"]]
        lo, hi = _widened(e)
        sides = [
            (a, b) for a, b in ((lo - g, lo - 1), (hi + 1, hi + g)) if _P0 <= a and b < _P0 + _SPAN
        ]
        options = []
        for user in [e["src"]] if e["src"] else range(16):
            covers = [
                _widened(x)
                for x in table
                if x["enabled"] and x["ns"] == e["ns"] and x["src"] in (0, user)
            ]
            options += [(user, free) for a, b in sides if (free := _free(a, b, covers))]
        if options:
            out[e["idx"]] = options
    return out


def _range_pin_ok(p: dict) -> bool:
    return (
        p["gold"]["entry"] is None
        and p["fails"][p["target"]] == {"range"}
        and "nomatch_range" in p["cells"]
    )


def _range_pins(rng: random.Random, table: list[dict], order: list[dict]) -> list[dict] | None:
    """One no-match probe per window of `range_windows`, at a drawn side, AxUSER[3:0] and word,
    on a channel whose bit the entry sets; None when one of them does not classify as the
    pinned range probe (the table is then redrawn)."""
    pins = []
    windows = range_windows(table)
    for e in order:
        options = windows.get(e["idx"])
        if options is None:
            continue
        user, parts = rng.choice(options)
        k = rng.randrange(sum((b + 1 - a) // 8 for a, b in parts))
        for a, b in parts:
            if k < (b + 1 - a) // 8:
                addr = a + 8 * k
                break
            k -= (b + 1 - a) // 8
        channels = [w for w, bit in ((0, e["read"]), (1, e["write"])) if bit]
        p = {
            "kind": "pin_range",
            "target": e["idx"],
            "addr": addr,
            "ns": e["ns"],
            "user": user,
            "axlen": 0,
            "write": rng.choice(channels),
        }
        p.update(classify(table, p))
        if not _range_pin_ok(p):
            return None
        pins.append(p)
    return pins


def _pin(rng: random.Random, table: list[dict], kind: str, e: dict, addr_of, ns: int) -> dict:
    """A probe of `kind` aimed at entry `e` that matches no entry, fails only the pinned term on
    `e`, and holds the pinned cell; None when no drawn address gives one."""
    term, cell = _PINS[kind]
    channels = [w for w, bit in ((0, e["read"]), (1, e["write"])) if bit]
    if not channels:
        return None
    write = rng.choice(channels)
    for _ in range(_PIN_TRIES):
        p = {
            "kind": kind,
            "addr": addr_of(),
            "ns": ns,
            "user": e["src"] if e["src"] else rng.randrange(16),
            "axlen": 1 if kind == "pin_len" else 0,
            "write": write,
        }
        if not _in_span(p):
            continue
        p.update(classify(table, p))
        if cell in p["cells"] and p["fails"][e["idx"]] == {term}:
            return p
    return None


def _pins(rng: random.Random, table: list[dict]) -> list[dict] | None:
    """The pinned no-match probes of one set, or None when the table cannot hold all four."""

    def inside(e: dict):
        return lambda: _in_window(rng, e)

    order = rng.sample(table, len(table))
    enabled = [e for e in order if e["enabled"]]
    pins = _range_pins(rng, table, order)
    if not pins:
        return None
    for kind, cands, ns_of in (
        ("pin_disabled", [e for e in order if not e["enabled"]], lambda e: e["ns"]),
        ("pin_ns", enabled, lambda e: e["ns"] ^ 1),
        ("pin_len", [e for e in enabled if not e["burst"]], lambda e: e["ns"]),
    ):
        found = next(
            (p for e in cands if (p := _pin(rng, table, kind, e, inside(e), ns_of(e)))), None
        )
        if found is None:
            return None
        pins.append(found)
    return pins


def _set(rng: random.Random) -> tuple[list[dict], tuple[dict, dict], list[dict]]:
    """One rule table that holds all four pinned no-match probes, redrawn until it does."""
    for _ in range(_SET_TRIES):
        table, pair = _table(rng)
        pins = _pins(rng, table)
        if pins is not None:
            return table, pair, pins
    raise AssertionError(f"no rule table held the pinned no-match probes in {_SET_TRIES} tries")


def _twin_ok(key: dict, twin: dict) -> bool:
    """`twin` is the `lowest_key` probe `key` on the other channel, decided by the same lowest
    matching entry."""
    return (
        "lowest_key" in key["cells"]
        and twin["write"] != key["write"]
        and all(twin[f] == key[f] for f in ("addr", "ns", "user", "axlen"))
        and twin["gold"]["entry"] == key["gold"]["entry"]
        and len(twin["gold"]["matching"]) >= 2
    )


def _own_bit(table: list[dict], p: dict) -> int:
    """The bit for `p`'s channel of the lowest matching entry."""
    e = next(x for x in table if x["idx"] == p["gold"]["entry"])
    return e["write"] if p["write"] else e["read"]


def _other_channel(rng: random.Random, table: list[dict], probes: list[dict]) -> dict | None:
    """A pinned twin of one `lowest_key` probe of the set: the same address, AxPROT[1],
    AxUSER[3:0] and AxLEN on the other channel, decided by its own bit of the same lowest
    entry; a probe whose lowest entry sets the other channel's bit is preferred, so the twin is
    admitted where the probe is blocked. None when the set holds no `lowest_key` probe."""
    keys = [p for p in probes if "lowest_key" in p["cells"]]
    if not keys:
        return None
    flip = [k for k in keys if _own_bit(table, {**k, "write": k["write"] ^ 1})]
    key = rng.choice(flip or keys)
    twin = {f: key[f] for f in ("addr", "ns", "user", "axlen")}
    twin.update(kind="pin_other_channel", write=key["write"] ^ 1, key=probes.index(key))
    twin.update(classify(table, twin))
    assert _twin_ok(key, twin), f"other-channel twin {twin} of {key}"
    if _own_bit(table, twin):
        twin["cells"].add("lowest_other_channel")
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
            twin = _other_channel(rng, table, probes)
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
            assert 2 <= e["idx"] <= 15, f"entry index {e['idx']}"
            two_pages = e["burst"] and e["end"] // _PAGE - e["start"] // _PAGE == 1
            g = 8 if two_pages else _GRANULE[e["burst"]]
            assert e["start"] % g == 0 and (e["end"] + 1) % g == 0, f"edges of {e}"
            assert _P0 <= e["start"] <= e["end"] < _P0 + _SPAN, f"window of {e}"
        for p in s["probes"]:
            assert _in_span(p), f"probe 0x{p['addr']:x} off the span or across a page"
            assert p["axlen"] in _AXLENS and 0 <= p["user"] <= 15
        kinds = [p["kind"] for p in s["probes"]]
        windows = sorted(range_windows(table))
        ranged = [p for p in s["probes"] if p["kind"] == "pin_range"]
        targets = sorted(p["target"] for p in ranged)
        assert targets == windows, f"outside-granule pins on {targets}, windows {windows}"
        assert all(_range_pin_ok(p) for p in ranged), f"outside-granule pins {ranged}"
        for kind, (_, cell) in _PINS.items():
            pinned = [p for p in s["probes"] if p["kind"] == kind]
            assert pinned and (len(pinned) == 1 or kind == "pin_range"), f"{kind} in {kinds}"
            assert all(p["gold"]["entry"] is None and cell in p["cells"] for p in pinned), kind
        keys = [
            p
            for p in s["probes"]
            if "lowest_key" in p["cells"] and p["kind"] != "pin_other_channel"
        ]
        twins = [p for p in s["probes"] if p["kind"] == "pin_other_channel"]
        assert len(twins) == (1 if keys else 0), f"{len(twins)} other-channel twins, {len(keys)}"
        for p in twins:
            assert _twin_ok(s["probes"][p["key"]], p), f"other-channel twin {p}"
            assert ("lowest_other_channel" in p["cells"]) == bool(_own_bit(table, p)), f"twin {p}"
    assert any("lowest_other_channel" in p["cells"] for s in sets for p in s["probes"])


def _table_text(table: list[dict]) -> str:
    return ";".join(
        f"E{e['idx']}[en{e['enabled']} ns{e['ns']} b{e['burst']} r{e['read']} w{e['write']} "
        f"src{e['src']} 0x{e['start']:x}..0x{e['end']:x}]"
        for e in table
    )


class _HitWatch:
    """Accumulates the inbound hit vectors for each SYS_IN request (printed only)."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.clear()

    def clear(self) -> None:
        self.read = 0
        self.write = 0
        self.unresolved = 0

    async def run(self) -> None:
        dut = self.dut
        prev = {"read": 0, "write": 0}
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            for name, valid, hit in (
                ("read", dut.sys_axi_arvalid, dut.tb_inb_read_hit),
                ("write", dut.sys_axi_awvalid, dut.tb_inb_write_hit),
            ):
                if not (valid.value.is_resolvable and hit.value.is_resolvable):
                    self.unresolved += 1
                    continue
                if prev[name]:
                    setattr(self, name, getattr(self, name) | int(hit.value))
                prev[name] = int(valid.value)


class smc_infilt_rule_matrix_rand_test_seq(SmcCsrSeq):
    """Program four drawn inbound rule tables and grade their SYS_IN probes against them."""

    def __init__(self, name: str = "smc_infilt_rule_matrix_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.sys_accesses = 0
        self.probes = 0
        self.total = 0
        self.repeats = 0
        self.admitted = 0
        self.blocked = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._shadow: dict[int, int] = {}
        self._results: list[dict] = []
        self._programmed: set[int] = set()
        self._first: dict[int, list[int]] = {}
        self._watch = None
        self._wdata_no = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sig(sig) -> int:
        assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    async def _program(self, e: dict) -> None:
        word = entry_word(e)
        idx = e["idx"]
        await self.csr_write(f"IB{idx}_CFG", _reg("FILTER_CONFIG", idx), word, length=8)
        await self.csr_write(f"IB{idx}_START", _reg("START_ADDR", idx), e["start"], length=8)
        await self.csr_write(f"IB{idx}_END", _reg("END_ADDR", idx), e["end"], length=8)
        for reg, want in (
            ("FILTER_CONFIG", word | _RESET["FILTER_CONFIG"]),
            ("START_ADDR", e["start"]),
            ("END_ADDR", e["end"]),
        ):
            await self.csr_read(f"IB{idx}_{reg}_RB", _reg(reg, idx), expected=want, length=8)
        self._programmed.add(idx)

    async def _restore(self, idx: int, tag: str) -> list[int]:
        for reg in _REGS:
            await self.csr_write(f"{tag}_IB{idx}_{reg}", _reg(reg, idx), _RESET[reg], length=8)
        return [
            await self.csr_read(f"{tag}_IB{idx}_{reg}_RB", _reg(reg, idx), _RESET[reg], length=8)
            for reg in _REGS
        ]

    def _beats(self, p: dict) -> list[int]:
        return [p["addr"] + 8 * b for b in range(p["axlen"] + 1)]

    def _pack(self, addrs: list[int]) -> int:
        return sum(self._shadow[a] << (64 * i) for i, a in enumerate(addrs))

    async def _sys_in(
        self, tag: str, p: dict, user: int, wdata: int, graded: bool
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"sys_in_{tag}")
        item.op = SmcSysAxiOp.WRITE if p["write"] else SmcSysAxiOp.READ
        item.addr = p["addr"]
        item.length = 8
        item.beats = p["axlen"] + 1
        item.prot = _PROT_NS if p["ns"] else 0
        item.axi_user = user
        item.wdata = wdata
        item.timeout_ns = _AXI_BOUND_NS
        if not graded:
            item.allow_error = True
        elif not (p["gold"]["entry"] is not None and p["gold"]["allowed"]):
            item.allow_error = True
            item.expect_error = True
            if item.beats > 1:
                item.expected_resp = _DECERR
        elif not p["write"]:
            item.expected = self._pack(self._beats(p))
        self._watch.clear()
        await _OneShot(item, f"sys_in_{tag}_os").start(self.env.sys_in_axi_agent.sequencer)
        self.sys_accesses += 1
        assert not item.timed_out, f"{tag}: SYS_IN access expired after {_AXI_BOUND_NS} ns"
        assert self._watch.unresolved == 0, f"{tag}: X/Z on a SYS_IN valid or hit probe"
        return item

    async def _run_probe(self, set_no: int, n: int, p: dict) -> None:
        tag = f"T{set_no}P{n}"
        beats = self._beats(p)
        admit = p["gold"]["entry"] is not None and p["gold"]["allowed"]
        wdata = 0
        if p["write"]:
            words = []
            for b in beats:
                self._wdata_no += 1
                words.append(0xD0A7_0000_0000_0000 | (self._wdata_no << 32) | (b & 0xFFFF_FFFF))
            wdata = sum(w << (64 * i) for i, w in enumerate(words))
        before = self._pack(beats)
        item = await self._sys_in(tag, p, p["user"], wdata, graded=True)
        self.probes += 1
        hit = self._watch.write if p["write"] else self._watch.read
        want = _OKAY if admit else _DECERR
        assert item.resp_code == want, (
            f"{tag}: resp {item.resp_code}, golden {want} (matching {p['gold']['matching']}, "
            f"lowest {p['gold']['entry']}) for {self._cell(p)}"
        )
        if admit and not p["write"]:
            assert item.rdata == before, f"{tag}: rdata 0x{item.rdata:x}, want 0x{before:x}"
        if admit and p["write"]:
            for i, b in enumerate(beats):
                self._shadow[b] = (wdata >> (64 * i)) & ((1 << 64) - 1)
        for b in beats:
            await self.csr_read(f"{tag}_SPM_0x{b:x}", b, expected=self._shadow[b], length=8)
        if admit:
            self.admitted += 1
        else:
            self.blocked += 1
        rec = {
            "tag": tag,
            "p": p,
            "resp": item.resp_code,
            "hit": hit,
            "repeat": None,
        }
        if p["src_rel"]:
            upper = self.rng.randint(1, 0xFF)
            user = (p["user"] & 0xF) | (upper << 4)
            same = self._pack(beats) if p["write"] else 0
            rep = await self._sys_in(f"{tag}_HI", p, user, same, graded=False)
            self.repeats += 1
            rec["repeat"] = f"AxUSER 0x{user:03x} resp {rep.resp_code} rdata 0x{rep.rdata:x}"
            for b in beats:
                await self.csr_read(f"{tag}_HI_SPM_0x{b:x}", b, expected=self._shadow[b], length=8)
        self._results.append(rec)
        cocotb.log.info(
            "PROBE %s: %s golden entry %s allowed %s -> resp %d hit 0x%04x (hit printed)%s",
            tag,
            self._cell(p),
            p["gold"]["entry"],
            p["gold"]["allowed"],
            item.resp_code,
            hit,
            "" if rec["repeat"] is None else f"; repeat above AxUSER[3:0]: {rec['repeat']}",
        )

    @staticmethod
    def _cell(p: dict) -> str:
        return (
            f"{'wr' if p['write'] else 'rd'} 0x{p['addr']:x} AxLEN {p['axlen']} "
            f"AxPROT[1] {p['ns']} AxUSER[3:0] {p['user']}"
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
        top = cocotb.top
        edges = [0]

        async def _count() -> None:
            while True:
                await RisingEdge(top.clk_smc_i)
                edges[0] += 1

        counter = cocotb.start_soon(_count())
        await self.wait_fuse_sense_done(max_cycles=_FUSE_BOUND)
        counter.kill()
        fuse = [
            self._sig(s)
            for s in (top.tb_fuse_sense_done, top.tb_fuse_reset_n, top.tb_rst_warm_smc_clk_n)
        ]
        self._watch = _HitWatch(top)
        watcher = cocotb.start_soon(self._watch.run())

        # S1: draw, reset words beside the RDL (control), seed every probe word.
        sets, attempts = draw(self.rng)
        check_filters(sets)
        self.total = sum(len(s["probes"]) for s in sets)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d rule sets x %d drawn probes plus %d pinned (attempt %d): "
            "%s",
            self.seed,
            _SETS,
            _PROBES,
            self.total - _TOTAL,
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
                await self.csr_read(f"IB{idx}_{r}_AT_START", _reg(r, idx), length=8) for r in _REGS
            ]
            assert not words[0] & _ENTRY_ENABLED, f"inbound entry {idx} enabled at start"
            self._first[idx] = words
            if idx >= 2:
                reset_reads.append(
                    f"E{idx} " + " ".join(f"{r}=0x{w:x}" for r, w in zip(_REGS, words))
                )
                assert words == [_RESET[r] for r in _REGS], (
                    f"inbound entry {idx} before any write reads {reset_reads[-1]}, "
                    f"filter_ctrl.rdl reset words {[hex(_RESET[r]) for r in _REGS]}"
                )
        for s in sets:
            for p in s["probes"]:
                for b in self._beats(p):
                    self._shadow.setdefault(b, _seed_word(b))
        for addr, word in sorted(self._shadow.items()):
            await self.csr_write(f"SEED_0x{addr:x}", addr, word, length=8)
        for addr, word in sorted(self._shadow.items()):
            await self.csr_read(f"SEED_0x{addr:x}_RB", addr, expected=word, length=8)
        self._mark_step("S1")
        self._log_chk(
            "CHK-IFM-RESET",
            "inbound entries 2 to 15 before any write equal the RDL reset words: "
            f"{'; '.join(reset_reads)}; RDL reset words "
            f"FILTER_CONFIG=0x{_RESET['FILTER_CONFIG']:x} "
            f"START_ADDR=0x{_RESET['START_ADDR']:x} END_ADDR=0x{_RESET['END_ADDR']:x}; "
            f"{len(self._shadow)} probe words seeded over SEP_IN",
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

        # Step 3, on the step 2 probes: no matching entry blocks.
        nomatch = self._with("nomatch")
        assert nomatch and all(r["resp"] == _DECERR for r in nomatch)
        pinned = {k: [r for r in self._results if r["p"]["kind"] == k] for k in _PINS}
        for kind, recs in pinned.items():
            sets_hit = {r["tag"].split("P")[0] for r in recs}
            assert len(sets_hit) == _SETS and all(r["resp"] == _DECERR for r in recs), kind
        per_set = [len(range_windows(s["table"])) for s in sets]
        ranged = pinned["pin_range"]
        assert len(ranged) == sum(per_set), f"{len(ranged)} outside-granule pins, want {per_set}"
        assert all(_range_pin_ok(r["p"]) for r in ranged)
        kinds = sorted({r["p"]["kind"] for r in nomatch})
        self._log_chk(
            "CHK-IFM-NO-MATCH-BLOCK",
            f"drawn={kinds}; {len(nomatch)} probes matched no entry and answered DECERR with "
            f"their SPM words unchanged when read over SEP_IN; pin_range one per enabled window "
            f"with a permission bit set whose outside granule matches no entry ({per_set} per "
            f"set); pinned in every set: "
            + "; ".join(f"{k} {self._list(v)}" for k, v in pinned.items())
            + f"; all: {self._list(nomatch)}",
        )

        # Step 4, on the step 2 probes: the lowest matching entry decides.
        multi = self._with("multi_rd") + self._with("multi_wr")
        key = self._with("lowest_key")
        admit = self._with("lowest_admit")
        assert key and admit and self._with("multi_rd") and self._with("multi_wr")
        by_tag = {r["tag"]: r for r in self._results}
        pairs = []
        for r in [r for r in self._results if r["p"]["kind"] == "pin_other_channel"]:
            set_no = int(r["tag"][1:].split("P")[0])
            k = by_tag[f"T{set_no}P{r['p']['key']}"]
            e = next(x for x in sets[set_no]["table"] if x["idx"] == r["p"]["gold"]["entry"])
            bit = e["write"] if r["p"]["write"] else e["read"]
            assert _twin_ok(k["p"], r["p"]), f"{r['tag']} is no twin of {k['tag']}"
            assert k["resp"] == _DECERR and r["resp"] == (_OKAY if bit else _DECERR), (
                f"{k['tag']} resp {k['resp']} and its twin {r['tag']} resp {r['resp']} on "
                f"lowest entry E{e['idx']} (read_allowed {e['read']} write_allowed {e['write']})"
            )
            pairs.append(f"{k['tag']}/{r['tag']} E{e['idx']} bit {bit}")
        twins = sum(1 for s in sets for p in s["probes"] if p["kind"] == "pin_other_channel")
        assert pairs and len(pairs) == twins, f"{len(pairs)} other-channel pairs, want {twins}"
        assert any(p.endswith("bit 1") for p in pairs), f"no pair with the bit set: {pairs}"
        self._log_chk(
            "CHK-IFM-LOWEST-WINS",
            f"drawn=overlaps {[s['pair'] for s in sets]}; {len(multi)} probes matched two or more "
            f"entries and answered by the lowest one's bit for their channel; {len(key)} of them "
            f"were blocked by the lowest entry although a higher matching entry permits and "
            f"{len(admit)} admitted by the lowest entry although a higher matching entry denies; "
            f"pinned other-channel pairs, the blocked probe and its twin on the other channel "
            f"answered by the same lowest entry's own bit for it ({len(pairs)}, "
            f"{sum(p.endswith('bit 1') for p in pairs)} with that bit set): {'; '.join(pairs)}; "
            f"{self._list(multi)}",
        )

        # Step 5, on the step 2 probes: the source ID term.
        src = sorted(
            {
                id(r): r for c in ("src_equal", "src_differ", "src_wild") for r in self._with(c)
            }.values(),
            key=lambda r: r["tag"],
        )
        assert self._with("src_equal") and self._with("src_differ") and self._with("src_wild")
        repeats = [f"{r['tag']} {r['repeat']}" for r in self._results if r["repeat"]]
        self._log_chk(
            "CHK-IFM-SRC-ID",
            f"drawn=src_id cells equal {len(self._with('src_equal'))} differ "
            f"{len(self._with('src_differ'))} wildcard {len(self._with('src_wild'))}; every one "
            f"answered as the golden: {self._list(src)}; repeats with the value above "
            f"AxUSER[3:0] printed, not compared: {'; '.join(repeats)}",
        )

        # Step 6, on the step 2 probes: the address granule, entry_enabled, allow_ns and
        # allow_burst with AxLEN.
        terms = {t: self._with(f"term_{t}") for t in _TERMS}
        lens = {n: len(self._with(f"admit_len{n}")) for n in _AXLENS}
        widened = self._with("widened")
        assert all(terms.values()) and all(lens.values()) and widened
        graded = sorted(
            {id(r): r for v in terms.values() for r in v}.values(), key=lambda r: r["tag"]
        )
        self._log_chk(
            "CHK-IFM-MATCH-TERMS",
            "drawn="
            + ",".join(f"{t}:{len(v)}" for t, v in terms.items())
            + f"; admitted AxLEN counts {lens}; every probe answered the golden response with "
            f"the seeded word on every read beat in order and every admitted write landing its "
            f"words; probes whose response turns on one term of one entry: {self._list(graded)}; "
            f"probes decided inside a widened granule outside the programmed edges: "
            f"{self._list(widened)}",
        )

        # S7: entries back at their reset words, entries 0 and 1 untouched.
        final = []
        for idx in sorted(self._programmed):
            got = await self._restore(idx, "FINAL")
            final.append(f"E{idx}=" + "/".join(f"0x{w:x}" for w in got))
        for idx in (0, 1):
            for reg, want in zip(_REGS, self._first[idx]):
                await self.csr_read(f"IB{idx}_{reg}_FINAL", _reg(reg, idx), want, length=8)
        watcher.kill()
        self._mark_step("S7")
        self._log_chk(
            "CHK-IFM-RESTORE",
            f"entries 0 and 1 read as at start {self._first[0]} {self._first[1]}; programmed "
            f"entries read their reset words: {' '.join(final)}",
        )
        self._finish(fuse, edges[0])

    def _finish(self, fuse: list[int], edges: int) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: fuse-sense wait bound %d clk_smc_i (returned after %d, "
            "tb_fuse_sense_done %d tb_fuse_reset_n %d tb_rst_warm_smc_clk_n %d); every SEP_IN "
            "access under the driver guard of %d ns (%d accesses); every SYS_IN access under "
            "%d ns (%d accesses); expiry raises AssertionError",
            _FUSE_BOUND,
            edges,
            *fuse,
            self.cfg.axi_timeout_ns,
            self.accesses,
            _AXI_BOUND_NS,
            self.sys_accesses,
        )
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert tuple(c for c, _ in self._chk_marks) == tuple(c for c, _ in _CHECKERS)
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before step {step}"
        assert self.probes == self.total, f"{self.probes} SYS_IN probes, want {self.total}"
        assert self.admitted >= 1 and self.blocked >= 1, (self.admitted, self.blocked)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; %d SYS_IN probes (%d admitted, %d "
            "blocked) plus %d printed repeats; %d SEP_IN accesses; stamps %s",
            "<".join(_STEPS),
            ",".join(c for c, _ in self._chk_marks),
            self.probes,
            self.admitted,
            self.blocked,
            self.repeats,
            self.accesses,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
