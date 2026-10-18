# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap AxCACHE replacement, attribute hold across half writes and the shared table.

Spec sources: alias_remap.rdl REGION_START/END/ATTRS; fabric.adoc Alias Remapping, Fabric Topology.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import DMA_CONFIG_ENABLED_ND, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import jtag_axi_read, jtag_axi_write, output_responder_counts
from .smc_rdl_regmap import smc_reg_addr

_WORD = 8
_SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
_PAYLOAD = 0x1122_3344_5566_7788
_VALID = 1 << 63
_MASTER_CACHE = 0b0011
AXI_TIMEOUT_NS = 50_000
FUSE_BOUND = 200_000
COUNT_POLL_BOUND = 200
DMA_POLLS = 50
DMA_POLL_CYCLES = 20
_GROUP = 8
_DMA = {
    name: smc_reg_addr(f"DMA_CTRL_{name}_REG_ADDR")
    for name in (
        "CONFIG",
        "DONE_0",
        "NEXT_ID_0",
        "STATUS_0",
        "DST_ADDRESS_LO",
        "DST_ADDRESS_HI",
        "SRC_ADDRESS_LO",
        "SRC_ADDRESS_HI",
        "LENGTH_LO",
        "LENGTH_HI",
        "DST_STRIDE_LO",
        "DST_STRIDE_HI",
        "SRC_STRIDE_LO",
        "SRC_STRIDE_HI",
        "NUM_REPETITIONS_LO",
        "NUM_REPETITIONS_HI",
    )
}

# Region bounds (START inclusive, END non-inclusive) and the table words of the test.
_REGIONS = {
    2: (0x0200_2000, 0x0200_3000),
    4: (0x0200_6000, 0x0200_7000),
    5: (0x0201_0000, 0x0201_2000),
    6: (0x0201_4000, 0x0201_6000),
}
_ATTRS_R5 = 0x8300_0000_0040_0000
_ATTRS_R6 = 0x8300_0000_0050_0000
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_TERMS = (
    "CACHE_REPLACE",
    "CACHE_MISS",
    "CACHE_ZERO",
    "HOLD_OFFSET_HALF",
    "HOLD_UPPER_HALF",
    "SHARED_DMA",
    "SHARED_SIMULTANEOUS",
)
_CHECKERS = (
    ("CHK-ALIAS-CACHE-REPLACE-AW", "S2"),
    ("CHK-ALIAS-CACHE-REPLACE-AR", "S2"),
    ("CHK-ALIAS-CACHE-MISS", "S3"),
    ("CHK-ALIAS-CACHE-ZERO-OBSERVE", "S4"),
    ("CHK-ALIAS-ATTR-HOLD-OFFSET-HALF", "S5"),
    ("CHK-ALIAS-ATTR-HOLD-UPPER-HALF", "S6"),
    ("CHK-ALIAS-SHARED-DMA", "S7"),
    ("CHK-ALIAS-SHARED-SIMULTANEOUS", "S8"),
)
JTAG_ACCESSES = 21
ACCESS_FLOOR = 111


def _reg(kind: str, region: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_{kind}_BASE_ADDR", region)


class smc_alias_remap_attr_test_seq(SmcCsrSeq):
    """Program alias remap regions over SEP_IN and observe JTAG and DMA traffic at SYS_OUT."""

    def __init__(self, name: str = "smc_alias_remap_attr_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self.chk_seen: dict[str, str] = {}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._events: list[tuple[str, int, int]] = []
        self._watch_stop = False
        self._count_last = "unused"
        self._dma_last = "unused"
        self._dma_polls_used = 0
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
            for ch in ("aw", "ar"):
                sigs = [getattr(ifc, f"{ch}{n}") for n in ("valid", "ready", "addr", "cache")]
                assert all(s.value.is_resolvable for s in sigs), (
                    f"u_output_axi_if {ch} probes are X/Z"
                )
                valid, ready, addr, cache = (int(s.value) for s in sigs)
                if valid and ready:
                    self._events.append((ch, addr, cache))

    async def _wait_writes(self, want: int, label: str) -> None:
        for n in range(1, COUNT_POLL_BOUND + 1):
            have = output_responder_counts()[0]
            self._count_last = f"{label}: write_count {have}/{want} after {n - 1} clocks"
            if have == want:
                return
            assert have < want, f"{label}: tb_output_axi_write_count {have} passed {want}"
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: write_count never reached {want}; {self._count_last}")

    async def _set_region(self, region: int, attrs: int, bounds: bool = True) -> None:
        start, end = _REGIONS[region]
        if bounds:
            await self.csr_write(f"R{region}_START", _reg("START", region), start, _WORD)
            await self.csr_write(f"R{region}_END", _reg("END", region), end, _WORD)
            await self.csr_read(f"R{region}_START_RB", _reg("START", region), start, _WORD)
            await self.csr_read(f"R{region}_END_RB", _reg("END", region), end, _WORD)
        await self._set_attrs(region, attrs)

    async def _set_attrs(self, region: int, attrs: int) -> None:
        await self.csr_write(f"R{region}_ATTRS", _reg("ATTRS", region), attrs, _WORD)
        await self.csr_read(f"R{region}_ATTRS_RB", _reg("ATTRS", region), attrs, _WORD)

    async def _jtag_write(self, label: str, addr: int, land: int, cache: int) -> int:
        """JTAG write at ``addr``; the word lands at ``land`` and AW carries ``cache``."""
        self._probe_id += 1
        word = 0xC0DE_0000_0000_0000 | (self._probe_id << 32) | (addr & 0xFFFF_FFFF)
        for seed in {addr, land}:
            self.cfg.sys_out_mem.write_int(seed, _SENTINEL, _WORD)
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
        aws = [(a, c) for ch, a, c in self._events[mark:] if ch == "aw"]
        assert aws == [(land, cache)], (
            f"[{label}] AW (addr, cache) {[(hex(a), hex(c)) for a, c in aws]}, "
            f"want (0x{land:x}, 0x{cache:x})"
        )
        return cache

    async def _jtag_read(self, label: str, addr: int, land: int, cache: int) -> int:
        """JTAG read at ``addr``; the data comes from ``land`` and AR carries ``cache``."""
        self._probe_id += 1
        word = 0xBEE0_0000_0000_0000 | (self._probe_id << 32) | (addr & 0xFFFF_FFFF)
        for seed in {addr, land}:
            self.cfg.sys_out_mem.write_int(seed, _SENTINEL, _WORD)
        self.cfg.sys_out_mem.write_int(land, word, _WORD)
        mark = len(self._events)
        item = await jtag_axi_read(self, addr, expected=word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG read 0x{addr:x} resp {item.resp_code}"
        assert item.rdata == word, f"[{label}] read 0x{item.rdata:016x}, want 0x{word:016x}"
        ars = [(a, c) for ch, a, c in self._events[mark:] if ch == "ar"]
        assert ars == [(land, cache)], (
            f"[{label}] AR (addr, cache) {[(hex(a), hex(c)) for a, c in ars]}, "
            f"want (0x{land:x}, 0x{cache:x})"
        )
        return cache

    async def _observe_pair(self, label: str, addr: int) -> tuple[int, int]:
        """JTAG write at ``addr`` and read at ``addr + 8``; return (awcache, arcache) seen."""
        self._probe_id += 1
        word = 0xC0DE_0000_0000_0000 | (self._probe_id << 32) | (addr & 0xFFFF_FFFF)
        for seed in (addr, addr + _WORD):
            self.cfg.sys_out_mem.write_int(seed, _SENTINEL, _WORD)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        item = await jtag_axi_write(self, addr, word)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG write resp {item.resp_code}"
        await self._wait_writes(writes + 1, label)
        assert self.cfg.sys_out_mem.read_int(addr, _WORD) == word, f"[{label}] write landing"
        self.cfg.sys_out_mem.write_int(addr + _WORD, word ^ 1, _WORD)
        item = await jtag_axi_read(self, addr + _WORD, expected=word ^ 1)
        self.jtag_accesses += 1
        assert item.resp_code == 0, f"[{label}] JTAG read resp {item.resp_code}"
        events = self._events[mark:]
        aws = [c for ch, a, c in events if ch == "aw" and a == addr]
        ars = [c for ch, a, c in events if ch == "ar" and a == addr + _WORD]
        assert len(aws) == 1 and len(ars) == 1, f"[{label}] handshakes {events}"
        return aws[0], ars[0]

    async def _dma_start(self, src: int, dst: int, tag: str) -> int:
        baseline = await self.csr_read(f"DMA_DONE_BASE_{tag}", _DMA["DONE_0"])
        await self.csr_write(f"DMA_CONFIG_{tag}", _DMA["CONFIG"], DMA_CONFIG_ENABLED_ND)
        for name, value in (
            ("DST_ADDRESS_LO", dst & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", dst >> 32),
            ("SRC_ADDRESS_LO", src & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", src >> 32),
            ("LENGTH_LO", _WORD),
            ("LENGTH_HI", 0),
            ("DST_STRIDE_LO", 0),
            ("DST_STRIDE_HI", 0),
            ("SRC_STRIDE_LO", 0),
            ("SRC_STRIDE_HI", 0),
            ("NUM_REPETITIONS_LO", 1),
            ("NUM_REPETITIONS_HI", 0),
        ):
            await self.csr_write(f"DMA_{name}_{tag}", _DMA[name], value)
        await self.csr_read(f"DMA_NEXT_ID_{tag}", _DMA["NEXT_ID_0"])
        return baseline

    async def _dma_wait(self, baseline: int, tag: str) -> None:
        for n in range(1, DMA_POLLS + 1):
            done = await self.csr_read(f"DMA_DONE_POLL_{tag}", _DMA["DONE_0"])
            self._dma_last = f"{tag}: DONE {done} baseline {baseline} poll {n}/{DMA_POLLS}"
            self._dma_polls_used += 1
            if done > baseline:
                return
            await ClockCycles(cocotb.top.clk_smc_i, DMA_POLL_CYCLES)
        status = await self.csr_read(f"DMA_STATUS_{tag}", _DMA["STATUS_0"])
        raise AssertionError(f"DMA [{tag}] never completed; {self._dma_last}; STATUS 0x{status:x}")

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
        for region in _REGIONS:
            await self.csr_read(f"R{region}_ATTRS_RESET", _reg("ATTRS", region), 0, _WORD)
        self._mark_step("S1")

        # S2: region 2 replaces AxCACHE with 0xF, 0xB, 0x2.
        aw_seen: list[int] = []
        ar_seen: list[int] = []
        for k, cache in enumerate((0xF, 0xB, 0x2)):
            attrs = _VALID | (cache << 56)
            await self._set_region(2, attrs, bounds=(k == 0))
            aw_seen.append(await self._jtag_write(f"W_C{cache:X}", 0x0200_2100, 0x0200_2100, cache))
            ar_seen.append(await self._jtag_read(f"R_C{cache:X}", 0x0200_2108, 0x0200_2108, cache))
        self._mark_step("S2")
        self._log_chk(
            "CHK-ALIAS-CACHE-REPLACE-AW",
            f"region 2 hit at 0x02002100: awcache {','.join(hex(c) for c in aw_seen)} for "
            f"cacheable 0xF,0xB,0x2 (master drives 0x{_MASTER_CACHE:X}); words landed unchanged",
        )
        self._log_chk(
            "CHK-ALIAS-CACHE-REPLACE-AR",
            f"region 2 hit at 0x02002108: arcache {','.join(hex(c) for c in ar_seen)} for "
            "cacheable 0xF,0xB,0x2; read data matched the seeded words",
        )

        # S3: outside region 2 the initiator's AxCACHE passes.
        await self._set_attrs(2, _VALID | (0xF << 56))
        miss_w = await self._jtag_write("MISS_W", 0x0200_4100, 0x0200_4100, _MASTER_CACHE)
        miss_r = await self._jtag_read("MISS_R", 0x0200_4108, 0x0200_4108, _MASTER_CACHE)
        self._mark_step("S3")
        self._log_chk(
            "CHK-ALIAS-CACHE-MISS",
            f"write 0x02004100 awcache 0x{miss_w:X} and read 0x02004108 arcache 0x{miss_r:X} "
            f"outside region 2 (cacheable 0xF); expected 0x{_MASTER_CACHE:X}",
        )

        # S4: cacheable 0 is observe-only (the specification does not state the value).
        await self._set_attrs(2, _VALID)
        zero_aw, zero_ar = await self._observe_pair("ZERO", 0x0200_2110)
        assert zero_aw in (0, _MASTER_CACHE), f"awcache 0x{zero_aw:X} is neither 0 nor 0x3"
        assert zero_ar in (0, _MASTER_CACHE), f"arcache 0x{zero_ar:X} is neither 0 nor 0x3"
        self._mark_step("S4")
        self._log_chk(
            "CHK-ALIAS-CACHE-ZERO-OBSERVE",
            f"awcache=0x{zero_aw:X} arcache=0x{zero_ar:X} for a hit on valid region 2 with "
            "cacheable 0 (observe-only, not specified, measured)",
        )

        # S5: 4-byte write of the offset half holds cacheable and valid.
        await self._set_region(4, _VALID | (0xB << 56) | 0x0010_0000)
        attrs4 = _reg("ATTRS", 4)
        await self.csr_write("R4_ATTRS_LO", attrs4, 0x0020_0000, 4)
        want = _VALID | (0xB << 56) | 0x0020_0000
        got = await self.csr_read("R4_ATTRS_LO_RB", attrs4, want, _WORD)
        await self._jtag_write("HOLD_LO", 0x0200_6100, 0x0220_6100, 0xB)
        self._mark_step("S5")
        self._log_chk(
            "CHK-ALIAS-ATTR-HOLD-OFFSET-HALF",
            f"after the 4-byte write at +0 ATTRS read 0x{got:016X}; JTAG write 0x02006100 "
            "landed at 0x02206100 with awcache 0xB",
        )

        # S6: 4-byte write at +4 holds the offset.
        await self.csr_write("R4_ATTRS_HI", attrs4 + 4, 0x8200_0000, 4)
        want = _VALID | (0x2 << 56) | 0x0020_0000
        got = await self.csr_read("R4_ATTRS_HI_RB", attrs4, want, _WORD)
        await self._jtag_write("HOLD_HI", 0x0200_6108, 0x0220_6108, 0x2)
        self._mark_step("S6")
        self._log_chk(
            "CHK-ALIAS-ATTR-HOLD-UPPER-HALF",
            f"after the 4-byte write at +4 ATTRS read 0x{got:016X}; JTAG write 0x02006108 "
            "landed at 0x02206108 with awcache 0x2",
        )

        # S7: JTAG and DMA share region 5.
        await self._set_region(5, _ATTRS_R5)
        mem.write_int(0x0241_0100, _PAYLOAD, _WORD)
        mem.write_int(0x0201_0100, _SENTINEL, _WORD)
        mem.write_int(0x0201_0200, _SENTINEL, _WORD)
        mem.write_int(0x0241_0200, _SENTINEL, _WORD)
        await self._jtag_write("SHARED_JTAG", 0x0201_0010, 0x0241_0010, 0x3)
        writes, _ = output_responder_counts()
        mark = len(self._events)
        base = await self._dma_start(0x0201_0100, 0x0201_0200, "S7")
        await self._dma_wait(base, "S7")
        await self._wait_writes(writes + 1, "DMA_S7")
        landed = mem.read_int(0x0241_0200, _WORD)
        kept = mem.read_int(0x0201_0200, _WORD)
        assert landed == _PAYLOAD, f"DMA payload at 0x02410200 is 0x{landed:016x}"
        assert kept == _SENTINEL, f"untranslated 0x02010200 changed to 0x{kept:016x}"
        dma_ev = [(ch, hex(a), hex(c)) for ch, a, c in self._events[mark:]]
        self._mark_step("S7")
        self._log_chk(
            "CHK-ALIAS-SHARED-DMA",
            f"JTAG 0x02010010 landed at 0x02410010; DMA read 0x02410100 and wrote "
            f"0x{landed:016X} at 0x02410200, sentinel kept at 0x02010200; DMA handshakes {dma_ev}",
        )

        # S8: JTAG group in region 5 while a DMA copy runs in region 6.
        await self._set_region(6, _ATTRS_R6)
        mem.write_int(0x0251_4100, _PAYLOAD, _WORD)
        mem.write_int(0x0251_4200, _SENTINEL, _WORD)
        mem.write_int(0x0201_4200, _SENTINEL, _WORD)
        items = []
        for k in range(_GROUP):
            item = SmcSysAxiItem(f"shared_group_{k}")
            item.op = SmcSysAxiOp.WRITE
            item.addr = 0x0201_0300 + _WORD * k
            item.length = _WORD
            item.wdata = 0x5348_0000_0000_0000 | k
            items.append(item)
            mem.write_int(item.addr, _SENTINEL, _WORD)
            mem.write_int(0x0241_0300 + _WORD * k, _SENTINEL, _WORD)
        writes, _ = output_responder_counts()
        base = await self._dma_start(0x0201_4100, 0x0201_4200, "S8")
        group = SmcSysAxiGroupItem("shared_group", items)
        task = cocotb.start_soon(
            _OneShot(group, "shared_group_os").start(self.env.jtag_axi_agent.sequencer)
        )
        done_at_start = await self.csr_read("DMA_DONE_AT_GROUP_START", _DMA["DONE_0"])
        assert done_at_start == base, (
            f"DONE_0 {done_at_start} when the group started, want {base} (DMA still running)"
        )
        await task
        self.jtag_accesses += _GROUP
        self._group_last = f"{_GROUP} group writes completed"
        await self._dma_wait(base, "S8")
        await self._wait_writes(writes + _GROUP + 1, "SHARED_SIMULTANEOUS")
        for k, item in enumerate(items):
            assert item.resp_code == 0, f"group write {k} resp {item.resp_code}"
            at = 0x0241_0300 + _WORD * k
            got = mem.read_int(at, _WORD)
            assert got == item.wdata, f"group word {k}: 0x{at:x} holds 0x{got:016x}"
            own = mem.read_int(item.addr, _WORD)
            assert own == _SENTINEL, f"group word {k}: untranslated 0x{item.addr:x} is 0x{own:x}"
        landed = mem.read_int(0x0251_4200, _WORD)
        assert landed == _PAYLOAD, f"DMA payload at 0x02514200 is 0x{landed:016x}"
        kept = mem.read_int(0x0201_4200, _WORD)
        assert kept == _SENTINEL, f"untranslated 0x02014200 changed to 0x{kept:016x}"
        self._mark_step("S8")
        self._log_chk(
            "CHK-ALIAS-SHARED-SIMULTANEOUS",
            f"{_GROUP} JTAG words landed at 0x02410300+8k and DMA payload 0x{landed:016X} at "
            f"0x02514200; DONE_0 {base}->advanced (read {done_at_start} when the group started)",
        )

        # S9: every programmed word returns to its reset value.
        for region in _REGIONS:
            for kind in ("START", "END", "ATTRS"):
                await self.csr_write(f"R{region}_{kind}_RESTORE", _reg(kind, region), 0, _WORD)
                await self.csr_read(f"R{region}_{kind}_RESTORE_RB", _reg(kind, region), 0, _WORD)
        self._mark_step("S9")
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
            ("jtag_group_await", f"{AXI_TIMEOUT_NS}ns per item", self._group_last),
            ("output_write_count_poll", f"{COUNT_POLL_BOUND}clk_smc_i", self._count_last),
            (
                "dma_done_poll",
                f"{DMA_POLLS}x{DMA_POLL_CYCLES}clk_smc_i",
                f"{self._dma_last} ({self._dma_polls_used} polls)",
            ),
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
