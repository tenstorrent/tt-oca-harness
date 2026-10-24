# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_007 ANCHOR: smc_remap_region_offset_walk_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 92cf4012b2ae455ac9e6022c2de06d406e75b909869529282c10afa24f126dab
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 1 ENV: cocotb
"""Alias, M-mode and Xvisor remap register storage and one translated read per table.

Field layout (`alias_remap.adoc`): `region_start.start_addr` and
`region_end.end_addr` are [55:12] RW, reset 0; `region_attrs` has `valid` [63],
`cacheable` [59:56] and `offset` [55:12], all RW, reset 0. `output_remap.adoc`:
`region_attrs` has `valid` [63] and `offset` [55:0], RW, reset 0. Reserved bits
read back are logged only (SF-001 is open).

From SEP_IN the sequence reads every remap register at its reset, walks all-ones,
zero and a walking one through every address field of the 8 alias entries and
the offset of the 8 M-mode and 8 Xvisor entries, then sets and clears `valid` on
all 24 entries and `cacheable` on the alias entries, reading back after every
write. From the JTAG manager it then issues one read per table through a
programmed entry, through the same entry with `valid` clear, and (alias) at the
non-inclusive region end; the SYS_OUT responder's AR address, ARCACHE and the
returned word show where each read went (`alias_remap.adoc`, `fabric.adoc`
"8 x 1 MiB regions", "A transaction that hits an alias remap region carries
that region's AxCACHE value"). A SEP_IN read and write at each output window
answers DECERR and reaches no SYS_OUT transaction (`memmap.adoc`). Every
register ends at 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import LOCAL_BASE_RESET, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import output_responder_counts

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

import smc_reg as _regs  # noqa: E402

_WORD = 8
RESP_OKAY = 0
RESP_DECERR = 3
FUSE_BOUND = 200_000
_ENTRIES = range(8)

# alias_remap.adoc:26, :37, :47, :49, :50.
ALIAS_ADDR_FIELD = ((1 << 56) - 1) & ~((1 << 12) - 1)
ALIAS_VALID = 1 << 63
ALIAS_CACHEABLE = 0xF << 56
ALIAS_ATTRS_FIELDS = ALIAS_VALID | ALIAS_CACHEABLE | ALIAS_ADDR_FIELD
# output_remap.adoc:23, :25.
ORMP_VALID = 1 << 63
ORMP_OFFSET = (1 << 56) - 1
ORMP_FIELDS = ORMP_VALID | ORMP_OFFSET

# fabric.adoc:78-80: the M-mode and Xvisor windows sit 0x0100_0000 and
# 0x0180_0000 above the SMC base; each holds eight 1 MiB regions.
MMODE_WINDOW = 0x0100_0000
XVISOR_WINDOW = 0x0180_0000
REGION_BYTES = 0x10_0000

ALIAS_WORDS = (ALIAS_ADDR_FIELD, *(1 << b for b in range(12, 56)), 0x0)
ORMP_WORDS = (ORMP_OFFSET, 0x0, *(1 << b for b in range(56)))
assert len(ALIAS_WORDS) == 46 and len(ORMP_WORDS) == 58

# S6.
ALIAS_XLATE_ENTRY = 3
ALIAS_XLATE_START = 0x0000_0002_0000_0000
ALIAS_XLATE_END = ALIAS_XLATE_START + 0x2000
ALIAS_XLATE_OFFSET = 0x0000_0000_1000_0000
ALIAS_XLATE_PROBE = ALIAS_XLATE_START + 0x120
ALIAS_HIT_CACHE = 0xF
# S7 / S8: (label, window, entry, offset, translated SYS_OUT address).
OUTPUT_XLATE = (
    ("MMODE", MMODE_WINDOW, 5, 0x0000_0003_0050_0000, 0x0000_0003_0050_0340),
    ("XVISOR", XVISOR_WINDOW, 2, 0x0000_0004_0020_0000, 0x0000_0004_0020_0340),
)
XLATE_LOW = 0x340

_TERMS = (
    "SETUP",
    "RESET-READ",
    "ALIAS-WALK",
    "ALIAS-ATTR",
    "OUTPUT-WALK",
    "ALIAS-XLATE",
    "MMODE-XLATE",
    "XVISOR-XLATE",
    "RESTORED",
)
CHECKERS = (
    "CHK-REMAP-RESET",
    "CHK-REMAP-ALIAS-ADDR-WALK",
    "CHK-REMAP-ALIAS-ATTR",
    "CHK-REMAP-MMODE-WALK",
    "CHK-REMAP-XVISOR-WALK",
    "CHK-REMAP-ALIAS-XLATE",
    "CHK-REMAP-MMODE-XLATE",
    "CHK-REMAP-XVISOR-XLATE",
    "CHK-TIMEOUT-PATHS",
    "CHK-NONVAC",
)


def _alias(kind: str, entry: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_{kind}_BASE_ADDR", entry)


def _ormp(table: str, entry: int) -> int:
    return getattr(_regs, f"SMC_{table}_REMAP_{entry}__REGION_REGION_ATTRS_REG_ADDR")


# (label, address, documented-field mask) of all 40 remap registers.
ALIAS_REGS = tuple(
    (f"ALIAS{e}_{kind}", _alias(kind, e), mask)
    for e in _ENTRIES
    for kind, mask in (
        ("START", ALIAS_ADDR_FIELD),
        ("END", ALIAS_ADDR_FIELD),
        ("ATTRS", ALIAS_ATTRS_FIELDS),
    )
)
ORMP_REGS = tuple(
    (f"{table}{e}_ATTRS", _ormp(table, e), ORMP_FIELDS)
    for table in ("MMODE", "XVISOR")
    for e in _ENTRIES
)
ALL_REGS = ALIAS_REGS + ORMP_REGS
assert len(ALIAS_REGS) == 24 and len(ORMP_REGS) == 16
assert len({a for _l, a, _m in ALL_REGS}) == 40, "two remap registers share an address"


class smc_remap_region_offset_walk_test_seq(SmcCsrSeq):
    """Walk every remap address field from SEP_IN; translate one JTAG read per table."""

    def __init__(self, name: str = "smc_remap_region_offset_walk_test_seq") -> None:
        super().__init__(name)
        self.jtag_accesses = 0
        self.chk_seen: list[str] = []
        self._stamps: list[tuple[str, int, int]] = []
        self._events: list[tuple[str, int, int]] = []
        self._watch = False
        self._sep_last = "none"
        self._jtag_last = "none"
        self._fuse_last = "not sampled"
        self._reserved: dict[str, int] = {}

    def _mark(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} did nothing"
        self._stamps.append((term, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    def _note_reserved(self, leg: str, value: int, mask: int) -> None:
        self._reserved[leg] = self._reserved.get(leg, 0) | (value & ~mask & ((1 << 64) - 1))

    async def _sep(
        self, op: SmcSysAxiOp, label: str, addr: int, data: int = 0, resp: int = RESP_OKAY
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = _WORD
        item.wdata = data
        if resp != RESP_OKAY:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = resp
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._sep_last = f"{label} {op.value} 0x{addr:x} resp={item.resp_code}"
        assert item.resp_code == resp, (
            f"SEP_IN {op.value} {label} at 0x{addr:x} answered resp {item.resp_code}, "
            f"expected {resp}"
        )
        return item

    async def _rd(self, label: str, addr: int) -> int:
        return (await self._sep(SmcSysAxiOp.READ, label, addr)).rdata

    async def _wr(self, label: str, addr: int, data: int) -> None:
        await self._sep(SmcSysAxiOp.WRITE, label, addr, data)

    async def _jtag_read(self, label: str, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"jtag_rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += 1
        self._jtag_last = f"{label} read 0x{addr:x} resp={item.resp_code}"
        assert item.resp_code == RESP_OKAY, (
            f"[{label}] JTAG read at 0x{addr:x} answered resp {item.resp_code}, not OKAY"
        )
        return item

    async def _watch_output(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while self._watch:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for ch in ("aw", "ar"):
                sigs = [getattr(top, f"tb_output_axi_{ch}{n}") for n in ("valid", "ready", "addr")]
                cache = getattr(ifc, f"{ch}cache")
                assert all(s.value.is_resolvable for s in sigs + [cache]), (
                    f"SYS_OUT {ch} probes are X/Z"
                )
                valid, ready, addr = (int(s.value) for s in sigs)
                if valid and ready:
                    self._events.append((ch, addr, int(cache.value)))

    async def _xlate_read(self, label: str, addr: int, land: int, word: int) -> tuple[int, int]:
        """JTAG read at ``addr``: one AR at ``land``, no AW, and the word seeded there."""
        mark = len(self._events)
        item = await self._jtag_read(label, addr)
        events = self._events[mark:]
        ars = [(a, c) for ch, a, c in events if ch == "ar"]
        assert [a for a, _c in ars] == [land], (
            f"[{label}] read at 0x{addr:x} left SYS_OUT with AR {[hex(a) for a, _c in ars]}, "
            f"expected [0x{land:x}]"
        )
        assert not [e for e in events if e[0] == "aw"], f"[{label}] AW handshake {events}"
        assert item.rdata == word, (
            f"[{label}] read at 0x{addr:x} returned 0x{item.rdata:016x}; SYS_OUT 0x{land:x} "
            f"holds 0x{word:016x}"
        )
        return ars[0][1], item.axi_cache

    async def body(self) -> None:
        # S1.
        await self.wait_fuse_sense_done(FUSE_BOUND)
        fuse = cocotb.top.tb_fuse_sense_done.value
        assert fuse.is_resolvable and int(fuse) == 1, f"tb_fuse_sense_done is {fuse}"
        self._fuse_last = f"tb_fuse_sense_done={int(fuse)}"
        mem = self.cfg.sys_out_mem
        assert mem is not None, "SYS_OUT responder not bound"
        local_base = await self._rd("LOCAL_BASE", _regs.SMC_BASE_CONFIG_LOCAL_BASE_REG_ADDR)
        assert local_base == LOCAL_BASE_RESET, (
            f"LOCAL_BASE reads 0x{local_base:x}, the documented reset is 0x{LOCAL_BASE_RESET:x}"
        )
        reg_window = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
        assert smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - reg_window == MMODE_WINDOW
        assert smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR") - reg_window == XVISOR_WINDOW
        self._mark("SETUP", 1)

        await self._reset_reads()
        await self._alias_walk()
        await self._alias_attr()
        await self._output_walk()

        self._watch = True
        watcher = cocotb.start_soon(self._watch_output())
        await self._alias_xlate(mem)
        for leg in OUTPUT_XLATE:
            await self._output_xlate(mem, local_base, *leg)
        self._watch = False
        await watcher

        await self._restore()
        self._finish()

    async def _reset_reads(self) -> None:
        # S2: offset 0 of each remap block first, then all 40 registers.
        first = (
            ("ALIAS0_START", _alias("START", 0), ALIAS_ADDR_FIELD),
            ("MMODE0_ATTRS", _ormp("MMODE", 0), ORMP_FIELDS),
            ("XVISOR0_ATTRS", _ormp("XVISOR", 0), ORMP_FIELDS),
        )
        for label, addr, mask in first + ALL_REGS:
            got = await self._rd(f"{label}_RESET", addr)
            assert got & mask == 0, (
                f"{label} at 0x{addr:x} reads 0x{got:016x} at reset; its documented fields "
                f"(mask 0x{mask:016x}) reset to 0"
            )
            self._note_reserved("reset", got, mask)
        self._mark("RESET-READ", len(first) + len(ALL_REGS))
        self._chk(
            "CHK-REMAP-RESET",
            f"first-reads alias/mmode/xvisor OKAY fields=0, {len(ALL_REGS)}/40 registers "
            f"fields=0x0; reserved bits observed OR=0x{self._reserved['reset']:016x} "
            "(LINKED-ISSUE SF-001, logged only)",
        )

    async def _alias_walk(self) -> None:
        # S3.
        compares = 0
        for label, addr, mask in ALIAS_REGS:
            for k, word in enumerate(ALIAS_WORDS):
                await self._wr(f"{label}_W{k}", addr, word)
                got = await self._rd(f"{label}_W{k}_RB", addr)
                assert got & ALIAS_ADDR_FIELD == word, (
                    f"{label} at 0x{addr:x}: wrote 0x{word:016x}, read 0x{got:016x}; bits "
                    "[55:12] are RW"
                )
                self._note_reserved("alias-walk", got, mask)
                compares += 1
        assert compares == 8 * 3 * 46, f"{compares} alias address-field compares"
        self._mark("ALIAS-WALK", compares)
        self._chk(
            "CHK-REMAP-ALIAS-ADDR-WALK",
            f"8 entries x 3 regs x 46 words, {compares}/1104 [55:12] match, resp OKAY; "
            f"reserved [63:56]/[11:0] observed OR=0x{self._reserved['alias-walk']:016x} "
            "(LINKED-ISSUE SF-001, logged only)",
        )

    async def _alias_attr(self) -> None:
        # S4: start = end = 0 from S3.
        compares = 0
        legs = (
            ("VALID1", ALIAS_VALID, ALIAS_VALID),
            ("VALID0", 0, ALIAS_VALID),
            ("CACHE_F", ALIAS_CACHEABLE, ALIAS_CACHEABLE),
            ("CACHE_0", 0, ALIAS_CACHEABLE),
        )
        for e in _ENTRIES:
            addr = _alias("ATTRS", e)
            for name, word, field in legs:
                await self._wr(f"ALIAS{e}_{name}", addr, word)
                got = await self._rd(f"ALIAS{e}_{name}_RB", addr)
                assert got & field == word & field, (
                    f"ALIAS{e} ATTRS {name}: wrote 0x{word:016x}, read 0x{got:016x} "
                    f"(field 0x{field:016x})"
                )
                compares += 1
        assert compares == 32, f"{compares} alias attribute compares"
        self._mark("ALIAS-ATTR", compares)
        self._chk(
            "CHK-REMAP-ALIAS-ATTR",
            f"8 entries valid 1->0, cacheable 0xF->0x0, {compares}/32 match",
        )

    async def _output_walk(self) -> None:
        # S5: no JTAG traffic runs during the walk.
        rows = {}
        for table in ("MMODE", "XVISOR"):
            offsets = valids = 0
            for e in _ENTRIES:
                addr = _ormp(table, e)
                for k, word in enumerate(ORMP_WORDS):
                    await self._wr(f"{table}{e}_W{k}", addr, word)
                    got = await self._rd(f"{table}{e}_W{k}_RB", addr)
                    assert got & ORMP_OFFSET == word, (
                        f"{table}{e} at 0x{addr:x}: wrote offset 0x{word:014x}, read "
                        f"0x{got:016x}; offset [55:0] is RW"
                    )
                    self._note_reserved("output-walk", got, ORMP_FIELDS)
                    offsets += 1
                for name, word in (("VALID1", ORMP_VALID), ("VALID0", 0)):
                    await self._wr(f"{table}{e}_{name}", addr, word)
                    got = await self._rd(f"{table}{e}_{name}_RB", addr)
                    assert got & ORMP_VALID == word, (
                        f"{table}{e} {name}: wrote 0x{word:016x}, read 0x{got:016x}"
                    )
                    self._note_reserved("output-walk", got, ORMP_FIELDS)
                    valids += 1
            assert offsets == 464 and valids == 16, f"{table}: {offsets} offset, {valids} valid"
            rows[table] = (offsets, valids)
        self._mark("OUTPUT-WALK", sum(o + v for o, v in rows.values()))
        reserved = self._reserved["output-walk"]
        for table in ("MMODE", "XVISOR"):
            offsets, valids = rows[table]
            self._chk(
                f"CHK-REMAP-{table}-WALK",
                f"8 entries x 58 words {offsets}/464 offset match, valid 1->0 x{valids // 2}; "
                f"{offsets + valids}/480 compares; reserved [62:56] observed OR=0x{reserved:016x} "
                "(LINKED-ISSUE SF-001, logged only)",
            )

    async def _alias_xlate(self, mem) -> None:
        # S6.
        e = ALIAS_XLATE_ENTRY
        attrs = ALIAS_VALID | ALIAS_CACHEABLE | ALIAS_XLATE_OFFSET
        cleared = attrs & ~ALIAS_VALID
        for kind, word, mask in (
            ("START", ALIAS_XLATE_START, ALIAS_ADDR_FIELD),
            ("END", ALIAS_XLATE_END, ALIAS_ADDR_FIELD),
            ("ATTRS", attrs, ALIAS_ATTRS_FIELDS),
        ):
            await self._wr(f"ALIAS{e}_{kind}_XLATE", _alias(kind, e), word)
            got = await self._rd(f"ALIAS{e}_{kind}_XLATE_RB", _alias(kind, e))
            assert got & mask == word, f"ALIAS{e} {kind} read 0x{got:016x}, wrote 0x{word:016x}"
        hit_at = ALIAS_XLATE_PROBE + ALIAS_XLATE_OFFSET
        seeds = {
            hit_at: 0xA11A_0000_0000_0001,
            ALIAS_XLATE_PROBE: 0xA11A_0000_0000_0002,
            ALIAS_XLATE_END: 0xA11A_0000_0000_0003,
            ALIAS_XLATE_END + ALIAS_XLATE_OFFSET: 0xA11A_0000_0000_0004,
        }
        for at, word in seeds.items():
            mem.write_int(at, word, _WORD)

        hit_cache, _init = await self._xlate_read(
            "ALIAS_HIT", ALIAS_XLATE_PROBE, hit_at, seeds[hit_at]
        )
        assert hit_cache == ALIAS_HIT_CACHE, (
            f"[ALIAS_HIT] ARCACHE 0x{hit_cache:X}; the region's cacheable field is 0xF"
        )
        await self._wr(f"ALIAS{e}_ATTRS_VALID0", _alias("ATTRS", e), cleared)
        got = await self._rd(f"ALIAS{e}_ATTRS_VALID0_RB", _alias("ATTRS", e))
        assert got & ALIAS_ATTRS_FIELDS == cleared, f"ALIAS{e} ATTRS read 0x{got:016x}"
        miss_cache, init = await self._xlate_read(
            "ALIAS_VALID0", ALIAS_XLATE_PROBE, ALIAS_XLATE_PROBE, seeds[ALIAS_XLATE_PROBE]
        )
        assert miss_cache == init, (
            f"[ALIAS_VALID0] ARCACHE 0x{miss_cache:X}; a miss keeps the initiator's 0x{init:X}"
        )
        await self._wr(f"ALIAS{e}_ATTRS_VALID1", _alias("ATTRS", e), attrs)
        got = await self._rd(f"ALIAS{e}_ATTRS_VALID1_RB", _alias("ATTRS", e))
        assert got & ALIAS_ATTRS_FIELDS == attrs, f"ALIAS{e} ATTRS read 0x{got:016x}"
        end_cache, init_end = await self._xlate_read(
            "ALIAS_END", ALIAS_XLATE_END, ALIAS_XLATE_END, seeds[ALIAS_XLATE_END]
        )
        assert end_cache == init_end, (
            f"[ALIAS_END] ARCACHE 0x{end_cache:X}; end is outside the region, so the "
            f"initiator's 0x{init_end:X} is kept"
        )
        for kind, mask in (
            ("START", ALIAS_ADDR_FIELD),
            ("END", ALIAS_ADDR_FIELD),
            ("ATTRS", ALIAS_ATTRS_FIELDS),
        ):
            await self._wr(f"ALIAS{e}_{kind}_XLATE_CLR", _alias(kind, e), 0)
            got = await self._rd(f"ALIAS{e}_{kind}_XLATE_CLR_RB", _alias(kind, e))
            assert got & mask == 0, f"ALIAS{e} {kind} read 0x{got:016x}"
        self._mark("ALIAS-XLATE", 3)
        self._chk(
            "CHK-REMAP-ALIAS-XLATE",
            f"hit AR=0x{hit_at:x} cache=0x{hit_cache:X} data ok; valid0 AR=0x{ALIAS_XLATE_PROBE:x} "
            f"cache=0x{miss_cache:X} (initiator 0x{init:X}) data ok; end AR=0x{ALIAS_XLATE_END:x} "
            f"cache=0x{end_cache:X} data ok",
        )

    async def _output_xlate(
        self, mem, local_base: int, table: str, window: int, e: int, offset: int, hit_at: int
    ) -> None:
        # S7 / S8.
        probe = local_base + window + e * REGION_BYTES + XLATE_LOW
        addr = _ormp(table, e)
        hit_word = 0x0E7A_0000_0000_0001 | (e << 8)
        pass_word = 0x0E7A_0000_0000_0002 | (e << 8)
        mem.write_int(hit_at, hit_word, _WORD)
        mem.write_int(probe, pass_word, _WORD)
        await self._wr(f"{table}{e}_XLATE", addr, ORMP_VALID | offset)
        got = await self._rd(f"{table}{e}_XLATE_RB", addr)
        assert got & ORMP_FIELDS == ORMP_VALID | offset, f"{table}{e} read 0x{got:016x}"
        await self._xlate_read(f"{table}_HIT", probe, hit_at, hit_word)
        await self._wr(f"{table}{e}_XLATE_VALID0", addr, offset)
        got = await self._rd(f"{table}{e}_XLATE_VALID0_RB", addr)
        assert got & ORMP_FIELDS == offset, f"{table}{e} read 0x{got:016x}"
        await self._xlate_read(f"{table}_VALID0", probe, probe, pass_word)

        self.env.axi_monitor.expected_decerr_addrs.add(probe)
        counts = output_responder_counts()
        mark = len(self._events)
        await self._sep(SmcSysAxiOp.READ, f"{table}_WINDOW_RD", probe, resp=RESP_DECERR)
        await self._sep(
            SmcSysAxiOp.WRITE, f"{table}_WINDOW_WR", probe, 0xDEAD_0000_0000_0000, RESP_DECERR
        )
        after = output_responder_counts()
        assert after == counts and len(self._events) == mark, (
            f"[{table}_SEP_IN] SYS_OUT write/read counts {counts} -> {after}, handshakes "
            f"{self._events[mark:]}; the inbound window probe must not leave the SMC"
        )
        assert mem.read_int(probe, _WORD) == pass_word, (
            f"[{table}_SEP_IN] SYS_OUT 0x{probe:x} changed after the refused write"
        )

        await self._wr(f"{table}{e}_XLATE_CLR", addr, 0)
        got = await self._rd(f"{table}{e}_XLATE_CLR_RB", addr)
        assert got & ORMP_FIELDS == 0, f"{table}{e} read 0x{got:016x}"
        self._mark(f"{table}-XLATE", 4)
        name = "W" if table == "MMODE" else "V"
        self._chk(
            f"CHK-REMAP-{table}-XLATE",
            f"hit AR=0x{hit_at:x} data ok; valid0 AR={name}=0x{probe:x} data ok; SEP_IN rd/wr "
            f"DECERR, AR count +{after[1] - counts[1]}, AW count +{after[0] - counts[0]}",
        )

    async def _restore(self) -> None:
        # S9.
        for label, addr, mask in ALL_REGS:
            await self._wr(f"{label}_RESTORE", addr, 0)
            got = await self._rd(f"{label}_RESTORE_RB", addr)
            assert got & mask == 0, f"{label} at 0x{addr:x} reads 0x{got:016x} after the restore"
            self._note_reserved("restore", got, mask)
        self._mark("RESTORED", len(ALL_REGS))

    def _finish(self) -> None:
        # S10.
        bound = self.cfg.axi_timeout_ns
        waits = (
            ("fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last),
            ("sep_in_axi_access", f"{bound}ns", f"{self.accesses} done, last {self._sep_last}"),
            ("jtag_axi_access", f"{bound}ns", f"{self.jtag_accesses} done, last {self._jtag_last}"),
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits, "
            + " ".join(f"{n}=bound {b} last={s}" for n, b, s in waits)
            + "; expiry raises AssertionError in the driver or the wait, 0 expired",
        )
        assert tuple(t for t, _c, _s in self._stamps) == _TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert tuple(self.chk_seen) == CHECKERS[:-1], f"checker order {self.chk_seen}"
        self._chk(
            "CHK-NONVAC",
            " < ".join(_TERMS)
            + "; terms "
            + ", ".join(f"{t}(n={c})@{s}ns" for t, c, s in self._stamps)
            + f"; checker lines {','.join(self.chk_seen)}; SEP_IN accesses {self.accesses}, "
            f"JTAG accesses {self.jtag_accesses}",
        )
