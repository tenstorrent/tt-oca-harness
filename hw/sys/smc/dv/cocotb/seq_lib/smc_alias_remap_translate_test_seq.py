# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap translation: reset identity, offsets, region edges, carry and open-rule legs.

Spec sources: alias_remap.rdl REGION_START/END/ATTRS; fabric.adoc Alias Remapping.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import jtag_axi_read, jtag_axi_write, output_responder_counts

_WORD = 8
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_MASTER_CACHE = 0b0011
AXI_TIMEOUT_NS = 50_000
FUSE_BOUND = 200_000
COUNT_POLL_BOUND = 200
_GROUP = 12
_GROUP_BASE = 0x0200_5000
_OFF_OLD = 0x0020_0000
_OFF_NEW = 0x0030_0000

# Region words: (START, END, ATTRS).
_R3 = (0x0200_4000, 0x0200_6000, 0x8300_0000_0020_0000)
_R3_VALID_CLEAR = 0x0300_0000_0020_0000
_R3_NEW = 0x8300_0000_0030_0000
_R0 = (0x0200_8000, 0x0200_9000, 0x8300_0000_0010_0000)
_R7 = (0x0200_C000, 0x0200_D000, 0x8300_0000_0030_0000)
_R5 = (0x0000_FFFF_F000, 0x0001_0000_0000, 0x8300_0000_0000_1000)
_R1 = (0x0200_E000, 0x0200_F000, 0x8300_0000_0040_0000)
_R2 = (0x0200_E000, 0x0200_F000, 0x8300_0000_0050_0000)
_R4 = (0x0201_0000, 0x0201_0000, 0x8300_0000_0060_0000)
_R6 = (0x0201_2000, 0x0201_1000, 0x8300_0000_0070_0000)
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_TERMS = (
    "RESET_IDENTITY",
    "VALID0",
    "TRANSLATE",
    "EDGES",
    "CARRY",
    "OVERLAP",
    "EMPTY",
    "REPROGRAM",
    "CLEANED",
)
_CHECKERS = (
    ("CHK-ALIAS-RESET-IDENTITY", "S2"),
    ("CHK-ALIAS-VALID0-TRANSPARENT", "S3"),
    ("CHK-ALIAS-OFFSET-LOW12", "S4"),
    ("CHK-ALIAS-RD-WR", "S4"),
    ("CHK-ALIAS-RANGE-EDGES", "S5"),
    ("CHK-ALIAS-CARRY", "S6"),
    ("CHK-ALIAS-OVERLAP-OBSERVE", "S7"),
    ("CHK-ALIAS-EMPTY-REGION-OBSERVE", "S8"),
    ("CHK-ALIAS-REPROGRAM-OUTSTANDING", "S9"),
)
JTAG_ACCESSES = 30
ACCESS_FLOOR = 123


def _reg(kind: str, region: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_{kind}_BASE_ADDR", region)


class smc_alias_remap_translate_test_seq(SmcCsrSeq):
    """Program alias remap regions over SEP_IN and observe JTAG traffic at SYS_OUT."""

    def __init__(self, name: str = "smc_alias_remap_translate_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self.chk_seen: dict[str, str] = {}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._events: list[tuple[str, int, int]] = []
        self._hits = [0, 0]
        self._watch_stop = False
        self._count_last = "unused"
        self._group_last = "unused"
        self._probe_id = 0

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
            hits = (top.tb_remap_jtag_aw_hit, top.tb_remap_jtag_ar_hit)
            assert all(s.value.is_resolvable for s in hits), "tb_remap_jtag hit probes are X/Z"
            for i, sig in enumerate(hits):
                self._hits[i] |= int(sig.value)
            for ch in ("aw", "ar"):
                sigs = [getattr(top, f"tb_output_axi_{ch}{n}") for n in ("valid", "ready", "addr")]
                cache = getattr(ifc, f"{ch}cache")
                assert all(s.value.is_resolvable for s in sigs + [cache]), (
                    f"output {ch} probes are X/Z"
                )
                valid, ready, addr = (int(s.value) for s in sigs)
                if valid and ready:
                    self._events.append((ch, addr, int(cache.value)))

    async def _wait_writes(self, want: int, label: str) -> None:
        for n in range(1, COUNT_POLL_BOUND + 1):
            have = output_responder_counts()[0]
            self._count_last = f"{label}: write_count {have}/{want} after {n - 1} clocks"
            if have == want:
                return
            assert have < want, f"{label}: tb_output_axi_write_count {have} passed {want}"
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: write_count never reached {want}; {self._count_last}")

    async def _set_attrs(self, region: int, attrs: int) -> None:
        await self.csr_write(f"R{region}_ATTRS", _reg("ATTRS", region), attrs, _WORD)
        await self.csr_read(f"R{region}_ATTRS_RB", _reg("ATTRS", region), attrs, _WORD)

    async def _program(self, region: int, words: tuple[int, int, int], attrs: int | None = None):
        start, end, word = words
        await self.csr_write(f"R{region}_START", _reg("START", region), start, _WORD)
        await self.csr_write(f"R{region}_END", _reg("END", region), end, _WORD)
        await self.csr_read(f"R{region}_START_RB", _reg("START", region), start, _WORD)
        await self.csr_read(f"R{region}_END_RB", _reg("END", region), end, _WORD)
        await self._set_attrs(region, word if attrs is None else attrs)

    def _word(self, base: int, addr: int) -> int:
        self._probe_id += 1
        return base | (self._probe_id << 32) | (addr & 0xFFFF_FFFF)

    def _seed(self, *addrs: int) -> None:
        for addr in set(addrs):
            self.cfg.sys_out_mem.write_int(addr, _SENTINEL, _WORD)

    async def _write(self, label: str, addr: int, land: int, cache: int | None = None):
        """JTAG write at ``addr``; the word lands at ``land`` and AW shows ``land``."""
        word = self._word(0xC0DE_0000_0000_0000, addr)
        self._seed(addr, land)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        item = await jtag_axi_write(self, addr, word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG write 0x{addr:x} resp {item.resp_code}"
        await self._wait_writes(writes + 1, label)
        got = self.cfg.sys_out_mem.read_int(land, _WORD)
        assert got == word, f"[{label}] SYS_OUT 0x{land:x} holds 0x{got:016x}, want 0x{word:016x}"
        if land != addr:
            kept = self.cfg.sys_out_mem.read_int(addr, _WORD)
            assert kept == _SENTINEL, f"[{label}] SYS_OUT 0x{addr:x} changed to 0x{kept:016x}"
        events = self._events[mark:]
        aws = [(a, c) for ch, a, c in events if ch == "aw"]
        assert [a for a, _ in aws] == [land], f"[{label}] AW addresses {[hex(a) for a, _ in aws]}"
        assert not [e for e in events if e[0] == "ar"], f"[{label}] AR handshake {events}"
        if cache is not None:
            assert aws[0][1] == cache, f"[{label}] awcache 0x{aws[0][1]:X}, want 0x{cache:X}"
        return aws[0][1]

    async def _read(self, label: str, addr: int, land: int, cache: int | None = None):
        """JTAG read at ``addr``; AR shows ``land`` and the word seeded there returns."""
        word = self._word(0xBEE0_0000_0000_0000, addr)
        self._seed(addr, land)
        self.cfg.sys_out_mem.write_int(land, word, _WORD)
        mark = len(self._events)
        item = await jtag_axi_read(self, addr, expected=word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG read 0x{addr:x} resp {item.resp_code}"
        assert item.rdata == word, f"[{label}] read 0x{item.rdata:016x}, want 0x{word:016x}"
        events = self._events[mark:]
        ars = [(a, c) for ch, a, c in events if ch == "ar"]
        assert [a for a, _ in ars] == [land], f"[{label}] AR addresses {[hex(a) for a, _ in ars]}"
        assert not [e for e in events if e[0] == "aw"], f"[{label}] AW handshake {events}"
        if cache is not None:
            assert ars[0][1] == cache, f"[{label}] arcache 0x{ars[0][1]:X}, want 0x{cache:X}"
        return ars[0][1]

    async def _observe_write(self, label: str, addr: int, candidates: tuple[int, ...]):
        """JTAG write whose landing is printed; it must be one of ``candidates``."""
        word = self._word(0xC0DE_0000_0000_0000, addr)
        self._seed(*candidates)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        item = await jtag_axi_write(self, addr, word)
        self.jtag_accesses += 1
        await self._wait_writes(writes + 1, label)
        aws = [a for ch, a, _ in self._events[mark:] if ch == "aw"]
        landed = [a for a in candidates if self.cfg.sys_out_mem.read_int(a, _WORD) == word]
        assert len(landed) == 1 and aws == landed, (
            f"[{label}] write 0x{addr:x}: AW {[hex(a) for a in aws]}, "
            f"landed {[hex(a) for a in landed]}"
        )
        return item.resp_code, landed[0]

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        self._fuse_last = {}
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, sub).value
            assert sig.is_resolvable, f"{sub} is X/Z ({sig})"
            self._fuse_last[sub] = int(sig)
        watcher = cocotb.start_soon(self._watch_output())
        mem = self.cfg.sys_out_mem
        assert mem is not None, "SYS_OUT responder not bound"

        # S1: every region reads valid clear.
        for region in range(8):
            await self.csr_read(f"R{region}_ATTRS_RESET", _reg("ATTRS", region), 0, _WORD)
        self._mark_step("S1")

        # S2: identity at reset.
        w_cache = await self._write("IDENTITY_W", 0x0200_0100, 0x0200_0100, _MASTER_CACHE)
        r_cache = await self._read("IDENTITY_R", 0x0200_0108, 0x0200_0108, _MASTER_CACHE)
        self._mark_step("S2")
        self._log_chk(
            "CHK-ALIAS-RESET-IDENTITY",
            f"nothing programmed: write 0x02000100 landed at 0x02000100 (awaddr equal, awcache "
            f"0x{w_cache:X}); read 0x02000108 araddr equal, arcache 0x{r_cache:X}, seeded word "
            "returned (reset-word proof, two-state bench)",
        )

        # S3: region 3 programmed with valid clear stays transparent.
        await self._program(3, _R3, _R3_VALID_CLEAR)
        cache = await self._write("VALID0_W", 0x0200_4100, 0x0200_4100, _MASTER_CACHE)
        self._mark_step("S3")
        self._log_chk(
            "CHK-ALIAS-VALID0-TRANSPARENT",
            f"region 3 START/END/ATTRS 0x{_R3_VALID_CLEAR:016X} valid clear: write 0x02004100 "
            f"landed at 0x02004100 (not 0x02204100), awcache 0x{cache:X}",
        )

        # S4: regions 0, 3 and 7 valid; writes and reads translate and keep the low 12 bits.
        await self._program(0, _R0)
        await self._program(7, _R7)
        await self._set_attrs(3, _R3[2])
        cases = ((0x0200_87A8, 0x0210_87A8), (0x0200_5A50, 0x0220_5A50), (0x0200_C3F8, 0x0230_C3F8))
        landed = [await self._write(f"XLATE_W{k}", s, d) for k, (s, d) in enumerate(cases)]
        write_text = ", ".join(f"0x{s:08X}->0x{d:08X}" for s, d in cases)
        read_caches = [await self._read(f"XLATE_R{k}", s, d) for k, (s, d) in enumerate(cases)]
        self._mark_step("S4")
        self._log_chk(
            "CHK-ALIAS-OFFSET-LOW12",
            f"writes {write_text} landed with bits [11:0] kept, sources kept the sentinel "
            f"(awcache {','.join(hex(c) for c in landed)} printed)",
        )
        self._log_chk(
            "CHK-ALIAS-RD-WR",
            f"reads at the same sources issued araddr {', '.join(f'0x{d:08X}' for _, d in cases)} "
            "and returned the words seeded there "
            f"(arcache {','.join(hex(c) for c in read_caches)})",
        )

        # S5: first page, last page, REGION_END page and the page below REGION_START.
        edges = (
            (0x0200_4008, 0x0220_4008),
            (0x0200_5FF8, 0x0220_5FF8),
            (0x0200_6008, 0x0200_6008),
            (0x0200_3FF8, 0x0200_3FF8),
        )
        for k, (s, d) in enumerate(edges):
            await self._write(f"EDGE{k}", s, d)
        self._mark_step("S5")
        self._log_chk(
            "CHK-ALIAS-RANGE-EDGES",
            f"{', '.join(f'0x{s:08X}->0x{d:08X}' for s, d in edges)}; one AW per write, no AR",
        )

        # S6: carry into bit 32.
        await self._program(5, _R5)
        self._seed(0x0000_0000_07A8)
        await self._write("CARRY", 0x0000_FFFF_F7A8, 0x0001_0000_07A8)
        low = mem.read_int(0x0000_0000_07A8, _WORD)
        assert low == _SENTINEL, f"no-carry address 0x7A8 holds 0x{low:016x}"
        self._mark_step("S6")
        self._log_chk(
            "CHK-ALIAS-CARRY",
            "write 0x0000FFFFF7A8 landed at 0x0001000007A8 (carry into bit 32) and the no-carry "
            "address 0x7A8 kept the sentinel",
        )

        # S7: overlapping regions 1 and 2; the specification does not state the value.
        await self._program(1, _R1)
        await self._program(2, _R2)
        self._hits = [0, 0]
        resp, land = await self._observe_write(
            "OVERLAP", 0x0200_E010, (0x0240_E010, 0x0250_E010, 0x0290_E010)
        )
        self._mark_step("S7")
        self._log_chk(
            "CHK-ALIAS-OVERLAP-OBSERVE",
            f"write 0x0200E010 over regions 1 and 2: resp={resp} landed_at=0x{land:08X} "
            f"tb_remap_jtag_aw_hit_seen=0x{self._hits[0]:X} (not specified, measured)",
        )

        # S8: empty and inverted regions (observe-only, the specification does not state the value).
        await self._program(4, _R4)
        await self._program(6, _R6)
        shown = []
        for k, src in enumerate((0x0201_0010, 0x0201_1010, 0x0201_2010)):
            cand = (src, src + 0x0060_0000, src + 0x0070_0000)
            resp, land = await self._observe_write(f"EMPTY{k}", src, cand)
            assert resp == 0, f"[EMPTY{k}] write 0x{src:x} resp {resp}"
            shown.append(f"0x{src:08X}->0x{land:08X} (offset 0x{land - src:X})")
        self._mark_step("S8")
        self._log_chk(
            "CHK-ALIAS-EMPTY-REGION-OBSERVE",
            f"region 4 START=END, region 6 START above END: {', '.join(shown)}, all OKAY "
            "(not specified, measured, landing printed)",
        )

        # S9: offset of region 3 changes while a JTAG group is outstanding; the specification
        # does not state the value.
        await self._set_attrs(3, _R3[2])
        items = []
        for k in range(_GROUP):
            item = SmcSysAxiItem(f"reprogram_{k}")
            item.op = SmcSysAxiOp.WRITE
            item.addr = _GROUP_BASE + _WORD * k
            item.length = _WORD
            item.wdata = 0x7061_0000_0000_0000 | k
            items.append(item)
            self._seed(item.addr, item.addr + _OFF_OLD, item.addr + _OFF_NEW)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        aw0 = len([e for e in self._events if e[0] == "aw"])
        group = SmcSysAxiGroupItem("reprogram_group", items)
        task = cocotb.start_soon(
            _OneShot(group, "reprogram_group_os").start(self.env.jtag_axi_agent.sequencer)
        )
        await self.csr_write("R3_ATTRS_NEW", _reg("ATTRS", 3), _R3_NEW, _WORD)
        accepted = len([e for e in self._events if e[0] == "aw"]) - aw0
        done, _ = output_responder_counts()
        assert accepted >= 1, "no group write accepted when R3_ATTRS_NEW landed"
        assert done < writes + _GROUP, f"all {_GROUP} group writes complete before R3_ATTRS_NEW"
        await task
        self.jtag_accesses += _GROUP
        await self._wait_writes(writes + _GROUP, "REPROGRAM")
        self._group_last = f"{_GROUP} writes completed, write_count {writes + _GROUP}"
        await self.csr_read("R3_ATTRS_NEW_RB", _reg("ATTRS", 3), _R3_NEW, _WORD)
        landing = []
        for k, item in enumerate(items):
            assert item.resp_code == 0, f"group write {k} resp {item.resp_code}"
            old = mem.read_int(item.addr + _OFF_OLD, _WORD) == item.wdata
            new = mem.read_int(item.addr + _OFF_NEW, _WORD) == item.wdata
            own = mem.read_int(item.addr, _WORD) == item.wdata
            assert old != new and not own, f"write {k}: old {old}, new {new}, source {own}"
            landing.append("O" if old else "N")
        order = "".join(landing)
        assert "NO" not in order, f"new-to-old transition in {order}"
        assert order.count("ON") <= 1, f"landing order {order}"
        aws = [a for ch, a, _ in self._events[mark:] if ch == "aw"]
        want = [it.addr + (_OFF_OLD if c == "O" else _OFF_NEW) for it, c in zip(items, landing)]
        assert aws == want, f"AW addresses {[hex(a) for a in aws]} vs memory landing {order}"
        self._mark_step("S9")
        self._log_chk(
            "CHK-ALIAS-REPROGRAM-OUTSTANDING",
            f"{_GROUP} writes all OKAY; landing in issue order {order} (O +0x{_OFF_OLD:X}, "
            f"N +0x{_OFF_NEW:X}); not specified, measured",
        )

        # S10: clear START, END and ATTRS of every programmed region.
        for region in range(8):
            for kind in ("START", "END", "ATTRS"):
                await self.csr_write(f"R{region}_{kind}_CLR", _reg(kind, region), 0, _WORD)
                await self.csr_read(f"R{region}_{kind}_CLR_RB", _reg(kind, region), 0, _WORD)
        self._mark_step("S10")
        self._watch_stop = True
        await watcher
        self._finish()

    def _finish(self) -> None:
        waits = (
            ("tb_fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last["tb_fuse_sense_done"]),
            ("tb_fuse_reset_n", f"{FUSE_BOUND}clk_smc_i", self._fuse_last["tb_fuse_reset_n"]),
            (
                "tb_rst_warm_smc_clk_n",
                f"{FUSE_BOUND}clk_smc_i",
                self._fuse_last["tb_rst_warm_smc_clk_n"],
            ),
            ("sep_in_axi_access", f"{AXI_TIMEOUT_NS}ns", f"{self.accesses} accesses done"),
            ("jtag_axi_access", f"{AXI_TIMEOUT_NS}ns", f"{self.jtag_accesses} accesses done"),
            ("output_write_count_poll", f"{COUNT_POLL_BOUND}clk_smc_i", self._count_last),
            ("jtag_group_completion", f"{AXI_TIMEOUT_NS}ns", self._group_last),
        )
        text = " ".join(f"{n}={b} last={s}" for n, b, s in waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError",
            len(waits),
            text,
        )
        assert tuple(s for s, _ in self._stamps) == _STEPS, f"steps {self._stamps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        printed = tuple(c for c, _ in self._chk_marks)
        assert printed == tuple(c for c, _ in _CHECKERS), f"checker order {printed}"
        for (chk_id, step), (_, seen_at) in zip(_CHECKERS, self._chk_marks):
            assert seen_at >= _STEPS.index(step) + 1, f"{chk_id} printed before {step}"
        total = self.accesses + self.jtag_accesses
        assert total >= ACCESS_FLOOR, f"{total} accesses, floor {ACCESS_FLOOR}"
        self.chk_seen["CHK-TIMEOUT-PATHS"] = text
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; accesses %d (SEP_IN %d, "
            "JTAG %d) vs floor %d",
            " < ".join(_TERMS),
            ",".join(printed),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            total,
            self.accesses,
            self.jtag_accesses,
            ACCESS_FLOOR,
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
