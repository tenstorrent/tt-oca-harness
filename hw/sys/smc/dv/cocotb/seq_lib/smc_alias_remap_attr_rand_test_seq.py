# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded alias remap regions: translation, AxCACHE replacement, edges and valid clear.

Spec sources: alias_remap.rdl REGION_START/END/ATTRS; fabric.adoc Alias Remapping.

The seed draws four configurations of one to three valid regions plus one region programmed
with `valid` clear, and the probe addresses and AxCACHE values. JTAG writes and reads reach
the SYS_OUT responder; every AW and AR handshake is recorded with its address and AxCACHE.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import _ALIAS_REMAP_H, reg_field_encode, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import output_responder_counts

_WORD = 8
_PAGE = 0x1000
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_SENTINEL_BYTE = 0x5A
FUSE_BOUND = 200_000
COUNT_POLL_BOUND = 200
CONFIGS = 4
REGIONS_MIN = 1
REGIONS_MAX = 3
PAGES_MAX = 8
SLOT_PAGES = 128
SRC_BASE_PAGE = 0x0_2000
DST_PAGE_MIN = 0x0_4000
DST_PAGE_END = 0x3_F000
_APERTURES = ((0x4000_0000, 0x4100_0000), (0xC000_0000, 0xC100_0000))
_OFFSET_FIELD_PAGES = 1 << 44
COMPARED_ACCESSES = 50
_STEPS_HEAD = ("S1", "S2")
_STEPS_CFG = ("S3", "S4", "S5")
_STEPS_TAIL = ("S6", "S7")
_CHECKERS = (
    ("CHK-ALR-RESET-WORDS", "S1"),
    ("CHK-ALR-RESET-TRANSPARENT", "S2"),
    ("CHK-ALR-EDGE-MISS", "S4"),
    ("CHK-ALR-VALID-CLEAR", "S4"),
    ("CHK-ALR-HIT-TRANSLATE", "S5"),
    ("CHK-ALR-HIT-CACHE", "S5"),
    ("CHK-ALR-LOGGED", "S6"),
)


def _reg(kind: str, region: int) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_{kind}_BASE_ADDR", region
    )


def _outside_apertures(lo: int, hi: int) -> bool:
    return all(hi <= a or lo >= b for a, b in _APERTURES)


class _Region:
    def __init__(self, index: int, start_page: int, pages: int, offset: int, cache: int) -> None:
        self.index = index
        self.start_page = start_page
        self.pages = pages
        self.offset = offset
        self.cache = cache

    @property
    def start(self) -> int:
        return self.start_page * _PAGE

    @property
    def end(self) -> int:
        return (self.start_page + self.pages) * _PAGE

    def attrs(self, valid: bool) -> int:
        return reg_field_encode(
            _ALIAS_REMAP_H,
            "ALIAS_REMAP__REMAP_REGION",
            "REGION_ATTRS",
            valid=int(valid),
            cacheable=self.cache,
            offset=self.offset,
        )

    def translate(self, addr: int) -> int:
        return (((addr >> 12) + self.offset) << 12) | (addr & 0xFFF)

    def __str__(self) -> str:
        return (
            f"R{self.index}[0x{self.start:x},0x{self.end:x}) pages {self.pages} "
            f"offset 0x{self.offset:x} cacheable 0x{self.cache:x}"
        )


class _Probe:
    def __init__(self, label: str, addr: int, land: int, size: int, drv: int, want: int) -> None:
        self.label = label
        self.addr = addr
        self.land = land
        self.size = size
        self.drv = drv
        self.want = want

    def __str__(self) -> str:
        return (
            f"{self.label} 0x{self.addr:x}->0x{self.land:x} size {self.size} "
            f"drv 0x{self.drv:X} cache 0x{self.want:X}"
        )


class _Config:
    def __init__(self, valid: list[_Region], clear: _Region) -> None:
        self.valid = valid
        self.clear = clear
        self.misses: list[_Probe] = []
        self.hits: list[_Probe] = []


class smc_alias_remap_attr_rand_test_seq(SmcCsrSeq):
    """Program seeded alias remap regions over SEP_IN and probe them over JTAG."""

    def __init__(self, name: str = "smc_alias_remap_attr_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.compared = 0
        self.measured = 0
        self.hits = 0
        self.misses = 0
        self.chk_seen: dict[str, str] = {}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._events: list[tuple[str, int, int]] = []
        self._watch_stop = False
        self._count_last = "unused"
        self._probe_id = 0
        self._programmed: set[int] = set()
        self._fuse_last: dict[str, int] = {}
        self._hit_probes: list[_Probe] = []

    # -- plumbing ---------------------------------------------------------

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._stamps)))
        self.chk_seen[chk_id] = text

    async def _watch_output(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while not self._watch_stop:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for ch in ("aw", "ar"):
                sigs = [getattr(top, f"tb_output_axi_{ch}{n}") for n in ("valid", "ready", "addr")]
                cache = getattr(ifc, f"{ch}cache")
                assert all(s.value.is_resolvable for s in sigs + [cache]), (
                    f"output {ch} probes are X/Z"
                )
                valid, ready, addr = (int(s.value) for s in sigs)
                if valid and ready:
                    self._events.append((ch, addr, int(cache.value)))

    async def _wait_count(self, index: int, want: int, label: str) -> None:
        name = ("write_count", "read_count")[index]
        for n in range(1, COUNT_POLL_BOUND + 1):
            have = output_responder_counts()[index]
            self._count_last = f"{label}: {name} {have}/{want} after {n - 1} clocks"
            if have == want:
                return
            assert have < want, f"{label}: tb_output_axi_{name} {have} passed {want}"
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: {name} never reached {want}; {self._count_last}")

    async def _jtag(self, item: SmcSysAxiItem) -> SmcSysAxiItem:
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        return item

    def _value(self, size: int) -> int:
        self._probe_id += 1
        if size == 1:
            value = (0x81 + 0x26 * self._probe_id) & 0xFF
            return value ^ 0xFF if value == _SENTINEL_BYTE else value
        return (
            0xA11A_0000_0000_0000
            | (self._probe_id << 32)
            | ((self._probe_id * 0x9E37_79B9) & 0xFFFF_FFFF)
        )

    def _seed(self, size: int, *addrs: int) -> None:
        for addr in set(addrs):
            if size == 1:
                self.cfg.sys_out_mem.write(addr, bytes([_SENTINEL_BYTE]))
            else:
                self.cfg.sys_out_mem.write_int(addr, _SENTINEL, _WORD)

    def _mem(self, addr: int, size: int) -> int:
        return self.cfg.sys_out_mem.read_int(addr, size)

    def _item(self, label: str, op: SmcSysAxiOp, addr: int, size: int, cache: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"alr_{label}")
        item.op = op
        item.addr = addr
        item.length = size
        item.axi_cache = cache
        return item

    async def _write(self, label: str, addr: int, land: int, size: int, drv: int, want: int):
        """Compared JTAG write: lands at ``land`` with AxCACHE ``want``; the source keeps
        its sentinel when it is not the landing address."""
        value = self._value(size)
        self._seed(size, addr, land)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        item = self._item(label, SmcSysAxiOp.WRITE, addr, size, drv)
        item.wdata = value
        await self._jtag(item)
        self.compared += 1
        assert item.resp_code == 0, f"[{label}] JTAG write 0x{addr:x} resp {item.resp_code}"
        await self._wait_count(0, writes + 1, label)
        got = self._mem(land, size)
        assert got == value, f"[{label}] SYS_OUT 0x{land:x} holds 0x{got:x}, want 0x{value:x}"
        if land != addr:
            kept = self._mem(addr, size)
            want_kept = _SENTINEL_BYTE if size == 1 else _SENTINEL
            assert kept == want_kept, f"[{label}] SYS_OUT 0x{addr:x} changed to 0x{kept:x}"
        events = self._events[mark:]
        aws = [(a, c) for ch, a, c in events if ch == "aw"]
        assert [a for a, _ in aws] == [land], (
            f"[{label}] write 0x{addr:x}: AW addresses {[hex(a) for a, _ in aws]}, want 0x{land:x}"
        )
        assert not [e for e in events if e[0] == "ar"], f"[{label}] AR handshake {events}"
        assert aws[0][1] == want, f"[{label}] awcache 0x{aws[0][1]:X}, want 0x{want:X}"
        return aws[0][1]

    async def _read(self, label: str, addr: int, land: int, size: int, drv: int, want: int):
        """Compared JTAG read: AR at ``land`` with AxCACHE ``want``; the word seeded there
        returns."""
        value = self._value(size)
        self._seed(size, addr, land)
        self.cfg.sys_out_mem.write_int(land, value, size)
        _, reads = output_responder_counts()
        mark = len(self._events)
        item = self._item(label, SmcSysAxiOp.READ, addr, size, drv)
        item.expected = value
        await self._jtag(item)
        self.compared += 1
        assert item.resp_code == 0, f"[{label}] JTAG read 0x{addr:x} resp {item.resp_code}"
        assert item.rdata == value, f"[{label}] read 0x{item.rdata:x}, want 0x{value:x}"
        await self._wait_count(1, reads + 1, label)
        events = self._events[mark:]
        ars = [(a, c) for ch, a, c in events if ch == "ar"]
        assert [a for a, _ in ars] == [land], (
            f"[{label}] read 0x{addr:x}: AR addresses {[hex(a) for a, _ in ars]}, want 0x{land:x}"
        )
        assert not [e for e in events if e[0] == "aw"], f"[{label}] AW handshake {events}"
        assert ars[0][1] == want, f"[{label}] arcache 0x{ars[0][1]:X}, want 0x{want:X}"
        return ars[0][1]

    async def _pair(self, p: _Probe) -> str:
        await self._write(f"{p.label}_W", p.addr, p.land, p.size, p.drv, p.want)
        await self._read(f"{p.label}_R", p.addr, p.land, p.size, p.drv, p.want)
        return str(p)

    async def _observe(self, label: str, addr: int, cache: int) -> str:
        """Measured JTAG write and read: the handshake address and AxCACHE are printed."""
        shown = []
        for op in (SmcSysAxiOp.WRITE, SmcSysAxiOp.READ):
            mark = len(self._events)
            item = self._item(f"{label}_{op.value}", op, addr, _WORD, cache)
            item.wdata = self._value(_WORD)
            item.allow_error = True
            await self._jtag(item)
            self.measured += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            ch = "aw" if op is SmcSysAxiOp.WRITE else "ar"
            seen = [(a, c) for c_, a, c in self._events[mark:] if c_ == ch]
            text = ",".join(f"0x{a:x}/cache 0x{c:X}" for a, c in seen) or "none"
            shown.append(f"{op.value} resp {item.resp_code} {ch} {text}")
        return f"{label} 0x{addr:x}: " + "; ".join(shown)

    async def _program(self, region: _Region, valid: bool) -> None:
        i = region.index
        words = (("START", region.start), ("END", region.end), ("ATTRS", region.attrs(valid)))
        for kind, value in words:
            await self.csr_write(f"R{i}_{kind}", _reg(kind, i), value, _WORD)
        for kind, value in words:
            await self.csr_read(f"R{i}_{kind}_RB", _reg(kind, i), value, _WORD)
        self._programmed.add(i)

    async def _clear(self, indices) -> None:
        for i in sorted(indices):
            for kind in ("START", "END", "ATTRS"):
                await self.csr_write(f"R{i}_{kind}_CLR", _reg(kind, i), 0, _WORD)
                await self.csr_read(f"R{i}_{kind}_CLR_RB", _reg(kind, i), 0, _WORD)

    # -- draw -------------------------------------------------------------

    def _draw_region(self, index: int, slot: int, cache: int | None = None) -> _Region:
        rng = self.rng
        pages = rng.randint(1, PAGES_MAX)
        start = SRC_BASE_PAGE + slot * SLOT_PAGES + rng.randint(1, SLOT_PAGES - pages - 1)
        dst = rng.randint(DST_PAGE_MIN, DST_PAGE_END - pages)
        region = _Region(index, start, pages, dst - start, rng.randrange(16))
        if cache is not None:
            region.cache = cache
        return region

    def _draw(self) -> list[_Config]:
        rng = self.rng
        zero_cfg = rng.randrange(CONFIGS)
        configs = []
        for k in range(CONFIGS):
            count = rng.randint(REGIONS_MIN, REGIONS_MAX)
            indices = rng.sample(range(8), count + 1)
            valid = [
                self._draw_region(idx, slot, 0 if (k == zero_cfg and slot == 0) else None)
                for slot, idx in enumerate(indices[:count])
            ]
            clear = self._draw_region(indices[count], count)
            configs.append(_Config(valid, clear))
            self._draw_probes(k, configs[-1], k == zero_cfg)
        for cfg in configs:
            spans = sorted((r.start - _PAGE, r.end + _PAGE) for r in cfg.valid + [cfg.clear])
            caches = {r.cache for r in cfg.valid + [cfg.clear]}
            assert all(p.drv not in caches for p in cfg.misses), (
                f"a miss drives a region's cacheable {sorted(caches)}: "
                f"{[str(p) for p in cfg.misses]}"
            )
            for (a0, a1), (b0, _) in zip(spans, spans[1:]):
                assert a1 <= b0, f"regions overlap with their edge pages: {spans}"
            for r in cfg.valid + [cfg.clear]:
                lo, hi = r.start - _PAGE, r.translate(r.end - 1) + 1
                assert 0 < r.offset < _OFFSET_FIELD_PAGES, f"{r}: offset outside the field"
                assert r.start_page + r.offset + r.pages < _OFFSET_FIELD_PAGES, f"{r}: past bit 56"
                assert _outside_apertures(lo, r.end + _PAGE), f"{r}: source in an SMC aperture"
                assert _outside_apertures(r.translate(r.start), hi), f"{r}: target in an aperture"
                assert r.translate(r.start) >= r.end + _PAGE, f"{r}: target overlaps the source"
        return configs

    # -- steps ------------------------------------------------------------

    def _draw_probes(self, k: int, cfg: _Config, zero: bool) -> None:
        """`zero` pins the first-byte hit to the region whose `cacheable` is 0."""
        rng = self.rng

        def drv_hit(region: _Region) -> int:
            return rng.choice([c for c in range(16) if c != region.cache])

        def drv_miss() -> int:
            caches = {x.cache for x in cfg.valid + [cfg.clear]}
            return rng.choice([c for c in range(16) if c not in caches])

        r = rng.choice(cfg.valid)
        drv = drv_miss()
        cfg.misses.append(_Probe(f"C{k}_END_PAGE", r.end, r.end, _WORD, drv, drv))
        r = rng.choice(cfg.valid)
        drv = drv_miss()
        cfg.misses.append(_Probe(f"C{k}_BELOW_START", r.start - 1, r.start - 1, 1, drv, drv))
        drv = drv_miss()
        c = cfg.clear
        cfg.misses.append(_Probe(f"C{k}_VALID_CLEAR", c.start, c.start, _WORD, drv, drv))
        r = cfg.valid[0] if zero else rng.choice(cfg.valid)
        cfg.hits.append(
            _Probe(f"C{k}_FIRST", r.start, r.translate(r.start), _WORD, drv_hit(r), r.cache)
        )
        r = rng.choice(cfg.valid)
        addr = r.start + _WORD * rng.randrange(1, r.pages * _PAGE // _WORD - 1)
        cfg.hits.append(
            _Probe(f"C{k}_INTERIOR", addr, r.translate(addr), _WORD, drv_hit(r), r.cache)
        )
        r = rng.choice(cfg.valid)
        addr = r.end - 1
        cfg.hits.append(_Probe(f"C{k}_LAST", addr, r.translate(addr), 1, drv_hit(r), r.cache))

    async def _probe_config(self, cfg: _Config) -> tuple[list[str], list[str]]:
        misses = [await self._pair(p) for p in cfg.misses]
        self.misses += len(cfg.misses)
        self._mark_step("S4")
        hits = [await self._pair(p) for p in cfg.hits]
        self.hits += len(cfg.hits)
        self._hit_probes += cfg.hits
        self._mark_step("S5")
        return misses, hits

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, sub).value
            assert sig.is_resolvable, f"{sub} is X/Z ({sig})"
            self._fuse_last[sub] = int(sig)
        assert self.cfg.sys_out_mem is not None, "SYS_OUT responder not bound"
        watcher = cocotb.start_soon(self._watch_output())

        configs = self._draw()
        rng = self.rng
        reset_addr = (SRC_BASE_PAGE + 4 * SLOT_PAGES) * _PAGE + _WORD * rng.randrange(512)
        reset_cache = rng.randrange(16)
        overlap = rng.sample(range(8), 2)
        overlap_dst = rng.sample(range(DST_PAGE_MIN, DST_PAGE_END - 1), 2)
        overlap_cache = [rng.randrange(16) for _ in range(2)]
        carry_index = rng.randrange(8)
        carry_cache = rng.randrange(16)
        drawn = "; ".join(
            f"C{k}: "
            + ", ".join(str(r) for r in c.valid)
            + f"; valid clear {c.clear}; probes "
            + ", ".join(str(p) for p in c.misses + c.hits)
            for k, c in enumerate(configs)
        )
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %s; reset probe 0x%x cache 0x%X; overlap regions %s dst "
            "pages %s cacheable %s; carry region %d cacheable 0x%X",
            self.seed,
            drawn,
            reset_addr,
            reset_cache,
            overlap,
            [hex(p) for p in overlap_dst],
            overlap_cache,
            carry_index,
            carry_cache,
        )

        # S1: reset words of the eight regions, logged beside the RDL reset words.
        words = []
        for i in range(8):
            got = [
                await self.csr_read(f"R{i}_{k}_RESET", _reg(k, i), None, _WORD)
                for k in (
                    "START",
                    "END",
                    "ATTRS",
                )
            ]
            words.append(f"R{i} " + "/".join(f"0x{v:x}" for v in got))
            assert got == [0, 0, 0], (
                f"{words[-1]} before any write, alias_remap.rdl reset words 0x0/0x0/0x0"
            )
        self._mark_step("S1")
        self._log_chk(
            "CHK-ALR-RESET-WORDS",
            f"REGION_START/END/ATTRS of the eight regions before any write {words} equal the "
            "alias_remap.rdl reset words 0x0/0x0/0x0",
        )

        # S2: every region at its reset words.
        text = await self._pair(
            _Probe("RESET", reset_addr, reset_addr, _WORD, reset_cache, reset_cache)
        )
        self._mark_step("S2")
        self._log_chk(
            "CHK-ALR-RESET-TRANSPARENT",
            f"{text}: write and read reached SYS_OUT at their own address with their own "
            f"AxCACHE; drawn=address 0x{reset_addr:x} cache 0x{reset_cache:X}",
        )

        # S3 to S5 per configuration: program, edge and valid-clear probes, hit probes.
        miss_lines, hit_lines = [], []
        previous: set[int] = set()
        for k, cfg in enumerate(configs):
            await self._clear(previous)
            for region in cfg.valid:
                await self._program(region, True)
            await self._program(cfg.clear, False)
            previous = {r.index for r in cfg.valid} | {cfg.clear.index}
            self._mark_step("S3")
            misses, hits = await self._probe_config(cfg)
            miss_lines += misses
            hit_lines += hits
        await self._clear(previous)
        edge = [m for m in miss_lines if "VALID_CLEAR" not in m]
        vclear = [m for m in miss_lines if "VALID_CLEAR" in m]
        self._log_chk(
            "CHK-ALR-EDGE-MISS",
            f"{len(edge)} pairs passed untranslated with the driven AxCACHE, which differs from "
            f"every region's cacheable; drawn={edge}",
        )
        self._log_chk(
            "CHK-ALR-VALID-CLEAR",
            f"{len(vclear)} pairs inside regions written with valid clear passed untranslated "
            f"with the driven AxCACHE, which differs from every region's cacheable; "
            f"drawn={vclear}",
        )
        self._log_chk(
            "CHK-ALR-HIT-TRANSLATE",
            f"{len(hit_lines)} pairs reached SYS_OUT at bits [55:12] plus the drawn offset with "
            f"bits [11:0] kept, the word landed and returned there; drawn={hit_lines}",
        )
        zero_hits = [str(p) for p in self._hit_probes if p.want == 0]
        self._log_chk(
            "CHK-ALR-HIT-CACHE",
            f"{len(hit_lines)} pairs presented the region's cacheable as AxCACHE on AW and AR, "
            f"the driven AxCACHE differing; {len(zero_hits)} of them on a cacheable 0 region, "
            f"AxCACHE 0 expected: {zero_hits}; drawn={hit_lines}",
        )

        # S6: measured legs, printed and not compared.
        start_page = SRC_BASE_PAGE + 1
        regions = [
            _Region(overlap[n], start_page, 1, overlap_dst[n] - start_page, overlap_cache[n])
            for n in range(2)
        ]
        for region in regions:
            await self._program(region, True)
        over = await self._observe("OVERLAP", regions[0].start + 0x10, 0)
        await self._clear(overlap)
        carry = _Region(carry_index, start_page, 1, _OFFSET_FIELD_PAGES - start_page, carry_cache)
        await self._program(carry, True)
        carried = await self._observe("CARRY", carry.start + 0x10, 0)
        await self._clear({carry_index})
        self._mark_step("S6")
        self._log_chk(
            "CHK-ALR-LOGGED",
            f"not compared, no document states either: overlap of {regions[0]} and "
            f"{regions[1]}: {over}; offset sum past bit 55 with {carry}: {carried}",
        )

        # S7: every programmed region back to its reset words.
        await self._clear(self._programmed)
        self._mark_step("S7")
        self._watch_stop = True
        await watcher
        self._finish()

    def _finish(self) -> None:
        bound = self.cfg.axi_timeout_ns
        waits = (
            ("tb_fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last["tb_fuse_sense_done"]),
            ("sep_in_axi_access", f"{bound}ns", f"{self.accesses} accesses done"),
            (
                "jtag_axi_access",
                f"{bound}ns",
                f"{self.compared + self.measured} accesses done",
            ),
            ("output_count_poll", f"{COUNT_POLL_BOUND}clk_smc_i", self._count_last),
        )
        text = " ".join(f"{n}={b} last={s}" for n, b, s in waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(waits),
            text,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = text
        steps = _STEPS_HEAD + _STEPS_CFG * CONFIGS + _STEPS_TAIL
        assert tuple(s for s, _ in self._stamps) == steps, f"steps {self._stamps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        printed = tuple(c for c, _ in self._chk_marks)
        assert printed == tuple(c for c, _ in _CHECKERS), f"checker order {printed}"
        for (chk_id, step), (_, seen_at) in zip(_CHECKERS, self._chk_marks):
            last = max(i for i, (s, _) in enumerate(self._stamps) if s == step)
            assert seen_at > last, f"{chk_id} printed before the last {step}"
        assert self.compared == COMPARED_ACCESSES, f"{self.compared} compared JTAG accesses"
        assert self.hits >= 1 and self.misses >= 1, f"hits {self.hits} misses {self.misses}"
        zero = [p for p in self._hit_probes if p.want == 0]
        assert zero, f"no compared hit expected AxCACHE 0: {[str(p) for p in self._hit_probes]}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; compared JTAG accesses "
            "%d (want %d, hit pairs %d, %d of them expecting AxCACHE 0, miss pairs %d), "
            "measured %d",
            " < ".join(steps),
            ",".join(printed),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.compared,
            COMPARED_ACCESSES,
            self.hits,
            len(zero),
            self.misses,
            self.measured,
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
