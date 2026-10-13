# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Boundary sweep of the 24 SMC register islands that declare a past-extent response.

Contract SMC_REG_ISLAND_BOUNDARY_001, anchor smc_reg_island_boundary_sweep_test.
Scenarios ISL-PASTEXT-DECERR.S1-S9, ISL-PASTEXT-SLVERR.S1-S15.
Sources: smc.rdl (ocah_past_extent_resp), regs/gen/adoc/memory_map.adoc, regs/gen/py memory map.

Per island four words are probed over SEP_IN: the first word, the last decoded word, the first
past-extent word and the aperture-end word. Every address is derived from the generated memory
map and compared with the contract's table before the first probe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    CLOCK_GATE_CONTROL,
    CLOCK_GATE_CONTROL_RESET,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    smc_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq

AXI_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
OKAY, SLVERR, DECERR = 0, 2, 3
PAST_DATA = 0xBADCAB1E
ISLAND_COUNT = 24
REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
LOCAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
CHK_STEP = (
    ("CHK-ISL-SETUP-GOLDENS", "S1"),
    ("CHK-ISL-FIRST-WORD-RW", "S3"),
    ("CHK-ISL-LAST-DECODED-WORD-RW", "S5"),
    ("CHK-ISL-PASTEXT-READ-DECERR", "S6"),
    ("CHK-ISL-PASTEXT-WRITE-DECERR-CLASS", "S7"),
    ("CHK-ISL-PASTEXT-WRITE-SLVERR-CLASS", "S8"),
    ("CHK-ISL-PASTEXT-NOCHANGE", "S9"),
    ("CHK-ISL-TABLE", "S10"),
)
FENCE_TERMS = (
    "SETUP-GOLDENS < FIRST-WORD-RW < LAST-DECODED-WORD-RW < PASTEXT-READ-DECERR < "
    "PASTEXT-WRITE-DECERR-CLASS < PASTEXT-WRITE-SLVERR-CLASS < PASTEXT-NOCHANGE < TABLE"
)

RW = "rw"
HOLE = "hole"


@dataclass(frozen=True)
class Island:
    """Contract table row: offsets from BASE and the nature of the first and last word."""

    name: str
    unit: str
    first: int
    last: int
    past: int
    end: int
    first_nature: str
    last_nature: str
    write_resp: int


_D, _S = DECERR, SLVERR
ISLANDS = (
    Island("C0_WDT", "smc_cluster_core0_wdt", 0x0, 0x20, 0x24, 0x3FC, RW, RW, _D),
    Island("C1_WDT", "smc_cluster_core1_wdt", 0x400, 0x420, 0x424, 0x7FC, RW, RW, _D),
    Island("C2_WDT", "smc_cluster_core2_wdt", 0x800, 0x820, 0x824, 0xBFC, RW, RW, _D),
    Island("C3_WDT", "smc_cluster_core3_wdt", 0xC00, 0xC20, 0xC24, 0xFFC, RW, RW, _D),
    Island("DFX", "dfx_ctrl", 0xB800, 0xB814, 0xB818, 0xBFFC, "ro(sw=r)", RW, _D),
    Island(
        "MAILBOX", "smc_mailbox", 0x18000, 0x3784C, 0x37850, 0x37FFC, "ro(SF-009)", "ro(SF-009)", _D
    ),
    Island("DMA", "dma_ctrl", 0x38000, 0x38134, 0x38138, 0x381FC, RW, RW, _D),
    Island(
        "ZEROER",
        "zeroer_ctrl",
        0x38200,
        0x38214,
        0x38218,
        0x382FC,
        RW,
        "ro(rd_swacc/wr_swacc side effect)",
        _D,
    ),
    Island("CPUCTRL", "smc_cpu_ctrl", 0x39000, 0x392BC, 0x392C0, 0x39FFC, RW, RW, _D),
    Island("RESET", "smc_reset_unit", 0x2000, 0x20C8, 0x20CC, 0x27FC, HOLE, RW, _S),
    Island("MISC", "smc_misc_wrap", 0x2800, 0x2A08, 0x2A0C, 0x2FFC, RW, "ro(sw=r)", _S),
    Island("GPIO", "gpio_intf", 0x3000, 0x340C, 0x3410, 0x3FFC, RW, HOLE, _S),
    Island(
        "AVS",
        "smc_avsbus_controller",
        0x4000,
        0x4058,
        0x405C,
        0x4FFC,
        "ro(sw=w AVS command trigger)",
        RW,
        _S,
    ),
    Island("I2C", "smc_i2c_wrap", 0x5000, 0x5E08, 0x5E0C, 0x5FFC, "ro(SF-009)", "ro(SF-009)", _S),
    Island(
        "EFUSE_MAP", "smc_efuse_map", 0x7000, 0x73FC, 0x7400, 0x7FFC, "ro(woset lock bits)", RW, _S
    ),
    Island(
        "EFUSE_IF",
        "efuse_interface_ctrl",
        0x8000,
        0x8018,
        0x801C,
        0x8FFC,
        "ro(sw=w singlepulse error-clear triggers)",
        RW,
        _S,
    ),
    Island(
        "TELEM",
        "smc_telemetry_receiver_wrap",
        0x9000,
        0x92FC,
        0x9300,
        0x9FFC,
        "ro(SF-009)",
        "ro(SF-009)",
        _S,
    ),
    Island(
        "OCTS",
        "smc_system_timer_octs",
        0xA000,
        0xA020,
        0xA024,
        0xAFFC,
        "ro(singlepulse start trigger)",
        RW,
        _S,
    ),
    Island("BASECFG", "smc_base_config", 0x10000, 0x10048, 0x1004C, 0x11FFC, RW, RW, _S),
    Island("ALIAS", "smc_alias_remap", 0x12000, 0x120FC, 0x12100, 0x12FFC, RW, HOLE, _S),
    Island("MREMAP_OUT", "smc_mmode_remap", 0x13000, 0x1303C, 0x13040, 0x13FFC, RW, RW, _S),
    Island("XREMAP_OUT", "smc_xvisor_remap", 0x14000, 0x1403C, 0x14040, 0x14FFC, RW, RW, _S),
    Island(
        "INFLT",
        "smc_inbound_filter_ctrl",
        0x15000,
        0x151FC,
        0x15200,
        0x15FFC,
        "ro(woset lock field)",
        HOLE,
        _S,
    ),
    Island(
        "OUTFLT",
        "smc_outbound_filter_ctrl",
        0x16000,
        0x161FC,
        0x16200,
        0x16FFC,
        "ro(woset lock field)",
        HOLE,
        _S,
    ),
)


def _writable(nature: str) -> bool:
    return nature in (RW, HOLE)


def _name(resp: int | None) -> str:
    return AXI_RESP_NAME.get(resp, f"resp={resp}")


@dataclass
class Record:
    """Measured answers of one island, keyed by probe word."""

    reads: dict[str, tuple[int, int]] = field(default_factory=dict)
    writes: dict[str, int] = field(default_factory=dict)
    readbacks: dict[str, int] = field(default_factory=dict)
    accesses: int = 0


class smc_reg_island_boundary_sweep_test_seq(SmcDecodeProbeSeq):
    """First, last decoded, past-extent and aperture-end words of every past-extent island."""

    def __init__(self, name: str = "smc_reg_island_boundary_sweep_test_seq") -> None:
        super().__init__(name)
        self.base = LOCAL_BASE_RESET
        self.addr: dict[str, dict[str, int]] = {}
        self.rec = {isl.name: Record() for isl in ISLANDS}
        self.setup_accesses = 0
        self.stamps: list[tuple[str, int]] = []
        self.events: list[tuple[str, str]] = []
        self.chk_accesses: dict[str, int] = {}
        self._mark_accesses = 0
        self.golden: dict[str, int] = {}

    # --- fence ----------------------------------------------------------
    async def _done(self, step: str) -> None:
        if self.stamps and int(get_sim_time("ps")) <= self.stamps[-1][1]:
            await RisingEdge(cocotb.top.clk_smc_i)
        self.stamps.append((step, int(get_sim_time("ps"))))
        self.events.append(("step", step))

    def _chk(self, chk_id: str, step: str, fmt: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.events.append(("chk", chk_id))
        self.chk_accesses[chk_id] = self.accesses - self._mark_accesses
        self._mark_accesses = self.accesses
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    def _count(self, isl: Island) -> None:
        self.rec[isl.name].accesses += 1

    async def _read(self, isl: Island, word: str, key: str | None = None) -> tuple[int, int]:
        key = key or word
        addr = self.addr[isl.name][word]
        resp, data = await self.read_any(f"{isl.name}_{key}", addr)
        self._count(isl)
        assert resp is not None, f"{isl.name} {word} @ 0x{addr:08x}: no read response"
        assert isinstance(data, int), f"{isl.name} {word} @ 0x{addr:08x}: unresolved read data"
        self.rec[isl.name].reads[key] = (resp, data)
        return resp, data

    async def _read_decerr(self, isl: Island, word: str) -> int:
        addr = self.addr[isl.name][word]
        data = await self.read_decerr(f"{isl.name}_{word}", addr)
        self._count(isl)
        self.rec[isl.name].reads[word] = (DECERR, data)
        return data

    async def _write(self, isl: Island, word: str, data: int) -> int:
        addr = self.addr[isl.name][word]
        item = SmcSysAxiItem(f"wr_{isl.name}_{word}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._count(isl)
        assert not item.timed_out and item.resp_code is not None, (
            f"{isl.name} {word} @ 0x{addr:08x}: no write response"
        )
        self.rec[isl.name].writes[word] = item.resp_code
        return item.resp_code

    async def _identity_cycle(self, isl: Island, word: str, nature: str, step: str) -> None:
        resp, data = self.rec[isl.name].reads[word]
        if not _writable(nature):
            return
        bresp = await self._write(isl, word, data)
        assert bresp == OKAY, (
            f"{step} {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x}: identity write of "
            f"0x{data:08x} answered {_name(bresp)}"
        )
        rresp, back = await self._read(isl, word, f"{word}_rb")
        self.rec[isl.name].readbacks[word] = back
        assert rresp == OKAY and back == data, (
            f"{step} {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x}: read-back "
            f"{_name(rresp)} 0x{back:08x} after writing 0x{data:08x}"
        )

    # --- steps ----------------------------------------------------------
    def _derive(self) -> None:
        """Build the 24-island probe table from the generated memory map and check it."""
        assert len(ISLANDS) == ISLAND_COUNT, f"{len(ISLANDS)} islands in the table"
        mismatches = []
        for isl in ISLANDS:
            first, window_end = generated_window(isl.unit)
            extent = generated_decoded_extent(isl.unit)
            rresp, bresp = generated_past_extent_resp(isl.unit)
            derived = {
                "first": first,
                "last": first + extent - 4,
                "past": first + extent,
                "end": window_end & ~3,
            }
            listed = {"first": isl.first, "last": isl.last, "past": isl.past, "end": isl.end}
            for word, off in derived.items():
                if off != listed[word]:
                    mismatches.append(
                        f"{isl.name} {word}: generated map 0x{off:x}, contract 0x{listed[word]:x}"
                    )
            if (rresp, bresp) != ("DECERR", _name(isl.write_resp)):
                mismatches.append(
                    f"{isl.name} past-extent response: RDL {rresp}/{bresp}, contract "
                    f"DECERR/{_name(isl.write_resp)}"
                )
            self.addr[isl.name] = {w: LOCAL_BASE_RESET + o for w, o in derived.items()}
        assert not mismatches, "probe table differs from the generated map: " + "; ".join(
            mismatches
        )
        self.env.axi_monitor.expected_decerr_addrs.update(
            a for words in self.addr.values() for w, a in words.items() if w in ("past", "end")
        )
        decerr_class = [i for i in ISLANDS if i.write_resp == DECERR]
        assert len(decerr_class) == 9 and len(ISLANDS) - len(decerr_class) == 15, "class split"

    async def _s1(self) -> None:
        await self.wait_fuse_sense_done()
        reads = (
            ("REGION_SIZE", REGION_SIZE, REGION_SIZE_RESET, 8),
            ("LOCAL_BASE", LOCAL_BASE, LOCAL_BASE_RESET & 0xFFFF_FFFF, 4),
            ("GLOBAL_BASE", GLOBAL_BASE, GLOBAL_BASE_RESET & 0xFFFF_FFFF, 4),
            ("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, CLOCK_GATE_CONTROL_RESET, 8),
        )
        for label, addr, reset, length in reads:
            resp, data = await self.read_any(f"S1_{label}", addr, length)
            self.setup_accesses += 1
            assert resp == OKAY, f"S1 {label} @ 0x{addr:08x} answered {_name(resp)}"
            assert data == reset, f"S1 {label} reads 0x{data:x}, generated reset 0x{reset:x}"
            self.golden[label] = data
        assert self.base == self.golden["LOCAL_BASE"], "LOCAL_BASE differs from the map base"
        self._derive()
        await self._done("S1")
        self._chk(
            "CHK-ISL-SETUP-GOLDENS",
            "S1",
            "REGION_SIZE 0x%x, LOCAL_BASE 0x%x, GLOBAL_BASE 0x%x and CLOCK_GATE_CONTROL 0x%x read "
            "OKAY, each equal to its generated RDL reset; %d islands tabulated (%d DECERR-write, "
            "%d SLVERR-write)",
            self.golden["REGION_SIZE"],
            self.golden["LOCAL_BASE"],
            self.golden["GLOBAL_BASE"],
            self.golden["CLOCK_GATE_CONTROL"],
            len(self.addr),
            sum(i.write_resp == DECERR for i in ISLANDS),
            sum(i.write_resp == SLVERR for i in ISLANDS),
        )

    async def _decoded_reads(self, word: str, step: str, hole_nature) -> None:
        for isl in ISLANDS:
            resp, data = await self._read(isl, word)
            addr = self.addr[isl.name][word]
            assert resp == OKAY, f"{step} {isl.name} {word} @ 0x{addr:08x} answered {_name(resp)}"
            if hole_nature(isl) == HOLE:
                assert data == 0, f"{step} {isl.name} hole @ 0x{addr:08x} reads 0x{data:x}"

    def _decoded_values(self, word: str, nature) -> str:
        parts = []
        for isl in ISLANDS:
            rec = self.rec[isl.name]
            _resp, data = rec.reads[word]
            wr = rec.writes.get(word)
            written = (
                f"W={_name(wr)},rb=0x{rec.readbacks[word]:08x}" if wr is not None else "no-write"
            )
            parts.append(
                f"{isl.name}@0x{self.addr[isl.name][word] - self.base:x}={nature(isl)}:"
                f"OKAY,0x{data:08x},{written}"
            )
        return "; ".join(parts)

    async def _s2(self) -> None:
        await self._decoded_reads("first", "S2", lambda i: i.first_nature)
        await self._done("S2")

    async def _s3(self) -> None:
        for isl in ISLANDS:
            await self._identity_cycle(isl, "first", isl.first_nature, "S3")
        await self._done("S3")
        ro = [f"{i.name}={i.first_nature}" for i in ISLANDS if not _writable(i.first_nature)]
        written = sum(_writable(i.first_nature) for i in ISLANDS)
        self._chk(
            "CHK-ISL-FIRST-WORD-RW",
            "S3",
            "first word of %d islands answered OKAY (RESET hole OKAY,0x%x); %d rw or hole words "
            "took the identity write with BRESP OKAY and read back the value read; %d ro words "
            "not written (%s); values: %s",
            len(ISLANDS),
            self.rec["RESET"].reads["first"][1],
            written,
            len(ro),
            ", ".join(ro),
            self._decoded_values("first", lambda i: i.first_nature),
        )

    async def _s4(self) -> None:
        await self._decoded_reads("last", "S4", lambda i: i.last_nature)
        await self._done("S4")

    async def _s5(self) -> None:
        for isl in ISLANDS:
            await self._identity_cycle(isl, "last", isl.last_nature, "S5")
        await self._done("S5")
        ro = [f"{i.name}={i.last_nature}" for i in ISLANDS if not _writable(i.last_nature)]
        written = sum(_writable(i.last_nature) for i in ISLANDS)
        wdt = ", ".join(
            f"{i.name} CMP rb=0x{self.rec[i.name].readbacks['last']:08x}"
            for i in ISLANDS
            if i.name.endswith("_WDT")
        )
        self._chk(
            "CHK-ISL-LAST-DECODED-WORD-RW",
            "S5",
            "last decoded word of %d islands answered OKAY (declared holes OKAY,0x0); %d rw or "
            "hole words took the identity write with BRESP OKAY and read back the value read; "
            "%d ro words not written (%s); watchdog state after the write (SF-003): %s; "
            "values: %s",
            len(ISLANDS),
            written,
            len(ro),
            ", ".join(ro),
            wdt,
            self._decoded_values("last", lambda i: i.last_nature),
        )

    async def _s6(self) -> None:
        for word in ("past", "end"):
            for isl in ISLANDS:
                data = await self._read_decerr(isl, word)
                assert data == PAST_DATA, (
                    f"S6 {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x} read 0x{data:x}"
                )
        await self._done("S6")
        self._chk(
            "CHK-ISL-PASTEXT-READ-DECERR",
            "S6",
            "the first past-extent word and the aperture-end word of %d islands read RRESP "
            "DECERR (%d) with rdata 0x%08x, %d of %d words; past offsets %s; end offsets %s",
            len(ISLANDS),
            DECERR,
            PAST_DATA,
            2 * len(ISLANDS),
            2 * ISLAND_COUNT,
            ",".join(f"{i.name}=0x{self.addr[i.name]['past'] - self.base:x}" for i in ISLANDS),
            ",".join(f"{i.name}=0x{self.addr[i.name]['end'] - self.base:x}" for i in ISLANDS),
        )

    async def _s7(self) -> None:
        words = 0
        for isl in (i for i in ISLANDS if i.write_resp == DECERR):
            for word in ("past", "end"):
                bresp = await self._write(isl, word, self.rec[isl.name].reads[word][1])
                assert bresp == DECERR, (
                    f"S7 {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x}: write answered "
                    f"{_name(bresp)}, the RDL declares DECERR"
                )
                words += 1
        await self._done("S7")
        self._chk(
            "CHK-ISL-PASTEXT-WRITE-DECERR-CLASS",
            "S7",
            "the first past-extent word and the aperture-end word of the %d DECERR-declared "
            "islands (%s) answered BRESP DECERR (%d), %d of 18 words",
            sum(i.write_resp == DECERR for i in ISLANDS),
            ",".join(i.name for i in ISLANDS if i.write_resp == DECERR),
            DECERR,
            words,
        )

    def _slverr_class(self) -> tuple[int, list[str], list[str]]:
        match, linked, table = 0, [], []
        for isl in (i for i in ISLANDS if i.write_resp == SLVERR):
            answers = []
            for word in ("past", "end"):
                bresp = self.rec[isl.name].writes[word]
                answers.append(f"{word}=0x{self.addr[isl.name][word] - self.base:x}:{_name(bresp)}")
                if bresp == SLVERR:
                    match += 1
                else:
                    linked.append(f"{isl.name}.{word}")
            table.append(f"{isl.name} " + " ".join(answers))
        return match, linked, table

    async def _s8(self) -> None:
        for isl in (i for i in ISLANDS if i.write_resp == SLVERR):
            for word in ("past", "end"):
                bresp = await self._write(isl, word, self.rec[isl.name].reads[word][1])
                assert bresp in (SLVERR, DECERR), (
                    f"S8 {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x}: write answered "
                    f"{_name(bresp)}, the RDL declares SLVERR and only DECERR is the known family"
                )
        await self._done("S8")
        match, linked, table = self._slverr_class()
        assert match + len(linked) == 30, f"S8 probed {match + len(linked)} of 30 words"
        self._chk(
            "CHK-ISL-PASTEXT-WRITE-SLVERR-CLASS",
            "S8",
            "%d match, %d LINKED-ISSUE of 30 words; RDL declares SLVERR (%d); DECERR answers are "
            "LINKED-ISSUE on RTL-2, RTL-3, DOC-4, DOC-7, SPEC-40 (main-tree issue record); "
            "mismatch table: %s; per island: %s",
            match,
            len(linked),
            SLVERR,
            ",".join(linked) or "none",
            "; ".join(table),
        )

    async def _s9(self) -> None:
        for word in ("past", "end"):
            for isl in ISLANDS:
                data = await self._read_decerr(isl, word)
                assert data == PAST_DATA, (
                    f"S9 {isl.name} {word} @ 0x{self.addr[isl.name][word]:08x} re-reads 0x{data:x}"
                )
        rw = [i for i in ISLANDS if i.last_nature == RW]
        for isl in rw:
            before = self.rec[isl.name].reads["last"][1]
            resp, data = await self._read(isl, "last", "last_again")
            assert resp == OKAY and data == before, (
                f"S9 {isl.name} last @ 0x{self.addr[isl.name]['last']:08x} re-reads "
                f"{_name(resp)} 0x{data:08x}, earlier 0x{before:08x}"
            )
        await self._done("S9")
        self._chk(
            "CHK-ISL-PASTEXT-NOCHANGE",
            "S9",
            "after the %d refused-write probes every past-extent and aperture-end word still "
            "reads DECERR,0x%08x (%d words) and %d rw last decoded words equal the value read "
            "before the writes; %d islands",
            sum(w in ("past", "end") for r in self.rec.values() for w in r.writes),
            PAST_DATA,
            2 * len(ISLANDS),
            len(rw),
            len(ISLANDS),
        )

    def _row(self, isl: Island, class_match: bool) -> str:
        rec = self.rec[isl.name]
        cells = []
        for word in ("first", "last", "past", "end"):
            resp, data = rec.reads[word]
            wr = rec.writes.get(word)
            cells.append(
                f"{word}@0x{self.addr[isl.name][word] - self.base:x} R={_name(resp)},"
                f"0x{data:08x} B={_name(wr) if wr is not None else '-'}"
            )
        return (
            f"{isl.name} [{' | '.join(cells)}] nature first={isl.first_nature} "
            f"last={isl.last_nature}; RDL write={_name(isl.write_resp)}; "
            f"{'match' if class_match else 'LINKED-ISSUE'}"
        )

    async def _s10(self) -> None:
        await self._done("S10")
        rows, match, linked = [], 0, 0
        for isl in ISLANDS:
            rec = self.rec[isl.name]
            assert all(w in rec.reads for w in ("first", "last", "past", "end")), (
                f"S10 {isl.name} has an unmeasured probe word"
            )
            ok = all(rec.writes[w] == isl.write_resp for w in ("past", "end"))
            rows.append(self._row(isl, ok))
            match += ok
            linked += not ok
        assert len(rows) == ISLAND_COUNT and match + linked == len(rows), (
            f"S10 table has {len(rows)} rows, {match} match, {linked} LINKED-ISSUE"
        )
        self._chk(
            "CHK-ISL-TABLE",
            "S10",
            "%d rows, %d match, %d LINKED-ISSUE; %s",
            len(rows),
            match,
            linked,
            " || ".join(rows),
        )
        self.chk_accesses["CHK-ISL-TABLE"] = sum(r.accesses for r in self.rec.values())

    @property
    def access_floor(self) -> int:
        """Accesses the contract table calls for, from the table and not from the run."""
        islands = len(ISLANDS)
        first = sum(_writable(i.first_nature) for i in ISLANDS)
        last = sum(_writable(i.last_nature) for i in ISLANDS)
        rw_last = sum(i.last_nature == RW for i in ISLANDS)
        setup, probe_reads, refused_writes, rereads = 4, 4 * islands, 2 * islands, 2 * islands
        return setup + probe_reads + refused_writes + rereads + rw_last + 2 * (first + last)

    def _fence(self) -> None:
        total = sum(r.accesses for r in self.rec.values())
        assert self.accesses == self.setup_accesses + total == self.access_floor, (
            f"{self.accesses} accesses, table holds {self.setup_accesses} setup + {total}, "
            f"floor {self.access_floor}"
        )
        printed = [c for k, c in self.events if k == "chk"]
        assert printed == [c for c, _s in CHK_STEP], f"checker lines printed {printed}"
        assert all(self.chk_accesses[c] > 0 for c in printed), f"zero access {self.chk_accesses}"
        assert [s for s, _t in self.stamps] == list(STEP_ORDER), f"steps {self.stamps}"
        times = [t for _s, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        for index, (kind, ident) in enumerate(self.events):
            if kind == "chk":
                step = dict(CHK_STEP)[ident]
                assert ("step", step) in self.events[:index], f"{ident} before step {step}"

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await self._s9()
        await self._s10()
        await self._done("S11")
        self._fence()
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; access counts %s; %d accesses = "
            "%d setup + %d table; stamps %s ps",
            FENCE_TERMS,
            ", ".join(c for c, _s in CHK_STEP),
            ", ".join(f"{c}={n}" for c, n in self.chk_accesses.items()),
            self.accesses,
            self.setup_accesses,
            self.accesses - self.setup_accesses,
            ", ".join(f"{s}={t}" for s, t in self.stamps),
        )
