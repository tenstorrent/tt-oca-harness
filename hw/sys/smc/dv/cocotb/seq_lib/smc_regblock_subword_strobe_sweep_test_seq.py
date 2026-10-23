# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_008 ANCHOR: smc_regblock_subword_strobe_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 6267422078430d380d02f714df24eeee005c62cb6d96000f1dd983845f6c5ecb
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 2 ENV: cocotb
"""Sub-word reads, byte-lane and strobed writes, and window sweeps of the generated register blocks.

Every access goes through SEP_IN, one at a time except the pipelined sub-word
and window read groups.

* One reference register of each of the 133 register-block instances (13
  families, counts from the generated address map) takes a full-width read,
  1-byte reads at every byte offset, 2-byte reads at every offset that stays in
  the register, and a second full-width read. The second read must equal the
  first, and outside the inbound filter (SF-006) it must equal the documented
  reset image. Sub-word data and RRESP are logged against the reference read
  (SF-009 is open).
* CPU_CTRL SCRATCH[0], START_ADDR of inbound and outbound entry 15, the system
  timer CTRL and telemetry receiver 0 CTRL take 1-byte writes; a neighbour
  register must not change and a full-width restore must read back the
  pre-leg value. The byte-lane readbacks are logged (SF-009, SF-031).
* REGION[7].region_attrs of the alias, M-mode and Xvisor remaps takes all ones
  and then 0; every documented field is compared, reserved bits are logged
  (SF-001).
* The system-timer window answers its 9 registers with their documented resets
  and DECERR 0xBADCAB1E past its 36-byte extent; the telemetry window answers
  OKAY over its 768-byte extent with exactly three words reading 0x1 and DECERR
  0xBADCAB1E past it (`memory_map.adoc`).
* FILTER_CONFIG of all 32 filter entries takes 8-byte writes with one byte lane
  strobed while every other lane carries the complement of the saved byte.
  `data_bus_width` must read 0x3 throughout. START_ADDR / END_ADDR must read
  the saved words until the allow_burst leg; after allow_burst = 1 they must
  read the saved words rounded to the 4 KB granule when both share one, else
  the saved words (`filter_ctrl.adoc` granule write-back); after allow_burst =
  0 they are logged. Full-width restores of FILTER_CONFIG, START_ADDR, END_ADDR
  and START_ADDR again must read back the saved words, and those readbacks are
  the reference words of the later legs. A WSTRB
  0x7F write with bit 63 set follows; the lock outcome is logged and an
  unlocked entry is restored. Outbound entry 15 then takes all ones and must
  read every documented field set and refuse the next write with DECERR. The
  other 31 entries are locked through lane 7 (full-width fallback if that does
  not lock) and must keep their saved configuration. Every write to a locked
  entry must answer DECERR and leave the three registers unchanged
  (`filter_ctrl.adoc`: `locked` is RW1S).
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    CLOCK_GATE_CONTROL,
    LOCAL_BASE_RESET,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    generated_decoded_extent,
    generated_window,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_rdl_regmap import RdlReg, rdl_contract, rdl_register

RESP_OKAY = 0
RESP_DECERR = 3
FUSE_BOUND = 200_000
ALL64 = (1 << 64) - 1
DEADSPACE_RDATA = 0xBADCAB1E
WINDOW_GROUP = 16

# S1: family -> (IP-XACT path of the reference register, documented count).
# A "{}" marks the instance index.
FAMILIES = (
    ("alias_remap", "smc_alias_remap[{}]/REGION/region_start", 8),
    ("mmode_remap", "smc_mmode_remap[{}]/REGION/region_attrs", 8),
    ("xvisor_remap", "smc_xvisor_remap[{}]/REGION/region_attrs", 8),
    ("inbound_filter", "smc_inbound_filter_ctrl[{}]/END_ADDR", 16),
    ("outbound_filter", "smc_outbound_filter_ctrl[{}]/END_ADDR", 16),
    ("gpio_intf", "gpio_intf[{}]/ACCESS_FILTER", 65),
    ("cpu_ctrl", "smc_cpu_ctrl/RESET_VECTOR[0]", 1),
    ("telemetry", "smc_telemetry_receiver_wrap/telemetry_receiver[{}]/STATUS", 3),
    ("timer", "smc_system_timer_octs/CTRL", 1),
    ("zeroer", "zeroer_ctrl/SIZE", 1),
    ("uart", "smc_uart_wrap/uart_log_engine_wrap[{}]/uart/LSR", 4),
    ("efuse_ctrl", "efuse_interface_ctrl/EFUSE_READ_REQ_TIMEOUT", 1),
    ("cla", "smc_cla/dst[{}]/Trdstcontrol", 1),
)
INSTANCES = 133
RESET_COMPARED = 117

# alias_remap.adoc:47, :49, :50; output_remap.adoc:23, :25.
ALIAS_ATTRS_FIELDS = (1 << 63) | (0xF << 56) | (((1 << 56) - 1) & ~((1 << 12) - 1))
ORMP_FIELDS = (1 << 63) | ((1 << 56) - 1)

# filter_ctrl.adoc:24-51.
F_LOCKED = 1 << 63
F_ALLOW_BURST = 1 << 24
F_GROUP_ID = 0xF << 20
F_SRC_ID = 0xF << 16
F_DBW = 0x7 << 12
F_ALLOW_NS = 1 << 8
F_ENTRY_EN = 1 << 4
F_WRITE = 1 << 1
F_READ = 1 << 0
F_DBW_VALUE = 0x3
F_RW = F_ALLOW_BURST | F_GROUP_ID | F_SRC_ID | F_ALLOW_NS | F_ENTRY_EN | F_WRITE | F_READ
F_DECLARED = F_LOCKED | F_RW | F_DBW
# S7: (strobed lane, byte written on it).
FILTER_LANE_LEGS = (
    (0, 0x01),
    (0, 0x00),
    (0, 0x02),
    (0, 0x00),
    (0, 0x10),
    (0, 0x00),
    (1, 0x01),
    (1, 0x00),
    (2, 0xFF),
    (2, 0x00),
    (3, 0x01),
    (3, 0x00),
)
FULLWIDTH_ENTRY = ("outbound", 15)
# S7: index of the leg that sets allow_burst, and the 4 KB granule it selects
# (filter_ctrl.adoc:31-34, :61-69).
BURST_SET_LEG = FILTER_LANE_LEGS.index((3, 0x01))
PAGE_MASK = 0xFFF
# S3: a preload of the target's own pre-leg value.
PRELOAD_PRE = -1

# system_timer_octs.adoc:32-116 (word offset -> name, documented reset of the
# declared fields); STATUS.MODE is NOT(is_primary_i).
TIMER_REGS = (
    ("TIMER_START", 0x0),
    ("CTRL", 0x0001_020A),
    ("STATUS", None),
    ("TIMER_PRESET_LO", 0x0),
    ("TIMER_PRESET_HI", 0x0),
    ("TIMER_COUNT_LO", 0x0),
    ("TIMER_COUNT_HI", 0x0),
    ("CREDIT_EXPIRED", 0x0),
    ("TIMER_GPIO_ENABLE", 0x0),
)
TIMER_STATUS_RUNNING = 1 << 4
TIMER_STATUS_MODE = 1 << 0
TIMER_EXTENT = 36
TIMER_APERTURE = 0x1000
# telemetry_receiver.adoc:21-28, :68; memory_map.adoc:44.
TELEM_EXTENT = 768
TELEM_APERTURE = 0x1000
TELEM_INSTANCES = 3

TERMS = (
    "SETUP",
    "SUBWORD",
    "BYTE-LANE",
    "FULLWIDTH-REMAP",
    "TIMER-WINDOW",
    "TELEM-WINDOW",
    "FILTER-LANES",
    "LOCK-UNSTROBED",
    "FULLWIDTH-FILTER",
    "LOCK-SET",
    "LOCKED-WRITES",
)
CHECKERS = (
    "CHK-SWEEP-SUBWORD",
    "CHK-SWEEP-BYTE-LANE",
    "CHK-SWEEP-FULLWIDTH-REMAP",
    "CHK-SWEEP-TIMER-WINDOW",
    "CHK-SWEEP-TELEM-WINDOW",
    "CHK-SWEEP-FCFG-LANES",
    "CHK-SWEEP-FULLWIDTH-FILTER",
    "CHK-SWEEP-LOCK-SET",
    "CHK-SWEEP-LOCKED-DECERR",
    "CHK-TIMEOUT-PATHS",
    "CHK-NONVAC",
)


def subword_plan(width: int) -> tuple[tuple[int, int], ...]:
    """(offset, length) of the S2 sub-word reads of a ``width``-byte register."""
    return tuple((o, 1) for o in range(width)) + tuple((o, 2) for o in range(width - 1))


@dataclass(frozen=True)
class Inst:
    name: str
    family: str
    reg: RdlReg

    @property
    def width(self) -> int:
        return self.reg.width_bytes


@dataclass(frozen=True)
class Entry:
    name: str
    cfg: int
    start: int
    end: int


def _count(template: str) -> int:
    n = 0
    while True:
        try:
            rdl_contract(template.format(n))
        except KeyError:
            return n
        n += 1


def build_instances() -> tuple[Inst, ...]:
    out: list[Inst] = []
    for family, template, documented in FAMILIES:
        n = _count(template) if "{}" in template else 1
        assert n == documented, (
            f"{family}: the generated map holds {n} instances of {template}, the contract "
            f"names {documented}"
        )
        for i in range(n):
            reg = rdl_register(template.format(i))
            assert reg.width_bytes in (4, 8), f"{reg.path} is {reg.width_bytes} bytes wide"
            out.append(Inst(f"{family}[{i}]", family, reg))
    assert len(out) == INSTANCES, f"{len(out)} instances, the contract names {INSTANCES}"
    assert len({i.reg.addr for i in out}) == INSTANCES, "two instances share an address"
    return tuple(out)


def build_entries() -> tuple[Entry, ...]:
    out = []
    for bank in ("inbound", "outbound"):
        for i in range(16):
            regs = [
                rdl_register(f"smc_{bank}_filter_ctrl[{i}]/{r}")
                for r in ("FILTER_CONFIG", "START_ADDR", "END_ADDR")
            ]
            out.append(Entry(f"{bank}{i}", *(r.addr for r in regs)))
    return tuple(out)


def _cfg_mask_check() -> None:
    reg = rdl_contract("smc_outbound_filter_ctrl[0]/FILTER_CONFIG")
    assert reg.declared_mask == F_DECLARED, (
        f"FILTER_CONFIG declared fields 0x{reg.declared_mask:016x}, filter_ctrl.adoc gives "
        f"0x{F_DECLARED:016x}"
    )


def _lane_image(word: int, lane: int, value: int) -> int:
    return (word & ~(0xFF << (8 * lane))) | (value << (8 * lane))


def _complement_with_lane(saved: int, lane: int, value: int) -> int:
    return _lane_image(~saved & ALL64, lane, value)


class smc_regblock_subword_strobe_sweep_test_seq(SmcCsrSeq):
    """Sub-word, byte-lane, strobed and window sweeps of the generated register blocks."""

    def __init__(self, name: str = "smc_regblock_subword_strobe_sweep_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self.branch_accesses = 0
        self.groups = 0
        self._stamps: list[tuple[str, int, int]] = []
        self._last = "none"
        self._fuse_last = "not sampled"
        self._reserved: dict[str, int] = {}
        self._saved: dict[str, tuple[int, int, int]] = {}
        self._locked: dict[str, tuple[int, int, int]] = {}
        self._unstrobed_locked: dict[str, int] = {}

    def _mark(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} did nothing"
        self._stamps.append((term, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    def _note_reserved(self, leg: str, value: int, mask: int) -> None:
        self._reserved[leg] = self._reserved.get(leg, 0) | (value & ~mask & ALL64)

    def _item(
        self,
        op: SmcSysAxiOp,
        label: str,
        addr: int,
        length: int,
        data: int = 0,
        wstrb: int | None = None,
        resp: int = RESP_OKAY,
        tolerate: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.wstrb = wstrb
        if resp != RESP_OKAY:
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = resp
        elif tolerate:
            item.allow_error = True
        return item

    def _check_resp(self, item: SmcSysAxiItem, resp: int) -> None:
        self._last = f"{item.get_name()} 0x{item.addr:x} resp={item.resp_code}"
        assert not item.timed_out, f"{item.get_name()} at 0x{item.addr:x} timed out"
        assert item.resp_code == resp, (
            f"SEP_IN {item.get_name()} at 0x{item.addr:x} answered resp {item.resp_code}, "
            f"expected {resp}"
        )

    async def _sep(
        self,
        op: SmcSysAxiOp,
        label: str,
        addr: int,
        length: int = 8,
        data: int = 0,
        wstrb: int | None = None,
        resp: int = RESP_OKAY,
    ) -> SmcSysAxiItem:
        item = self._item(op, label, addr, length, data, wstrb, resp)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._check_resp(item, resp)
        return item

    async def _rd(self, label: str, addr: int, length: int = 8) -> int:
        return (await self._sep(SmcSysAxiOp.READ, label, addr, length)).rdata

    async def _wr(
        self,
        label: str,
        addr: int,
        data: int,
        length: int = 8,
        wstrb: int | None = None,
        resp: int = RESP_OKAY,
    ) -> None:
        await self._sep(SmcSysAxiOp.WRITE, label, addr, length, data, wstrb, resp)

    async def _group(self, label: str, items: list[SmcSysAxiItem]) -> None:
        group = SmcSysAxiGroupItem(label, items)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(items)
        self.groups += 1
        for item in items:
            assert not item.timed_out, f"{item.get_name()} at 0x{item.addr:x} timed out"
        self._last = f"group {label} ({len(items)} reads)"

    async def body(self) -> None:
        # S1.
        await self.wait_fuse_sense_done(FUSE_BOUND)
        fuse = cocotb.top.tb_fuse_sense_done.value
        assert fuse.is_resolvable and int(fuse) == 1, f"tb_fuse_sense_done is {fuse}"
        self._fuse_last = f"tb_fuse_sense_done={int(fuse)}"
        primary = cocotb.top.tb_chiplet_is_primary.value
        assert primary.is_resolvable, f"tb_chiplet_is_primary is {primary}"
        self.is_primary = int(primary)
        self.cg_saved = await self._rd("CG_SAVE", CLOCK_GATE_CONTROL)
        cg = self.cg_saved & ~(UART_CG_EN | TELEMETRY_CG_EN)
        await self._wr("CG_UNGATE", CLOCK_GATE_CONTROL, cg)
        self.cg_ungated = await self._rd("CG_UNGATE_RB", CLOCK_GATE_CONTROL)
        cocotb.log.info(
            "S1 CLOCK_GATE_CONTROL saved 0x%016x wrote 0x%016x read 0x%016x (SF-030, logged)",
            self.cg_saved,
            cg,
            self.cg_ungated,
        )
        _cfg_mask_check()
        self.instances = build_instances()
        self.entries = build_entries()
        self._mark("SETUP", 3)

        await self._subword()
        await self._byte_lane()
        await self._fullwidth_remap()
        await self._timer_window()
        await self._telem_window()
        await self._filter_lanes()
        await self._lock_unstrobed()
        await self._fullwidth_filter()
        await self._lock_set()
        await self._locked_writes()
        self._finish()

    async def _subword(self) -> None:
        # S2.
        planned = sum(len(subword_plan(i.width)) for i in self.instances)
        done = stable = reset_ok = lane_bad = resp_bad = 0
        first_bad: list[str] = []
        families: dict[str, int] = {}
        for inst in self.instances:
            mask = (1 << (8 * inst.width)) - 1
            first = await self._rd(f"{inst.name}_REF0", inst.reg.addr, inst.width)
            plan = subword_plan(inst.width)
            items = [
                self._item(
                    SmcSysAxiOp.READ,
                    f"{inst.name}_B{o}L{n}",
                    inst.reg.addr + o,
                    n,
                    tolerate=True,
                )
                for o, n in plan
            ]
            await self._group(f"{inst.name}_SUBWORD", items)
            for (o, n), item in zip(plan, items):
                done += 1
                want = (first >> (8 * o)) & ((1 << (8 * n)) - 1)
                if item.resp_code != RESP_OKAY:
                    resp_bad += 1
                if item.rdata != want or item.resp_code != RESP_OKAY:
                    lane_bad += 1
                    if len(first_bad) < 6:
                        first_bad.append(
                            f"{inst.name}+{o}/{n}=0x{item.rdata:x}(ref 0x{want:x},"
                            f"resp {item.resp_code})"
                        )
            second = await self._rd(f"{inst.name}_REF1", inst.reg.addr, inst.width)
            assert second == first, (
                f"{inst.name} at 0x{inst.reg.addr:x}: full-width read 0x{first:x} before and "
                f"0x{second:x} after the sub-word reads"
            )
            stable += 1
            if inst.family != "inbound_filter":
                declared = inst.reg.declared_mask & mask
                want = inst.reg.reset_word & declared
                assert second & declared == want, (
                    f"{inst.name} ({inst.reg.path}) at 0x{inst.reg.addr:x} reads 0x{second:x}; "
                    f"its documented reset is 0x{want:x} over the declared fields "
                    f"0x{declared:x}"
                )
                self._note_reserved("subword", second, declared)
                reset_ok += 1
            families[inst.family] = families.get(inst.family, 0) + 1
        assert done == planned, f"{done} sub-word reads completed, the plan issues {planned}"
        assert stable == INSTANCES and reset_ok == RESET_COMPARED, (
            f"stable {stable}/{INSTANCES}, reset {reset_ok}/{RESET_COMPARED}"
        )
        self._mark("SUBWORD", done)
        self._chk(
            "CHK-SWEEP-SUBWORD",
            f"{len(self.instances)}/{INSTANCES} instances "
            f"({', '.join(f'{k}={v}' for k, v in families.items())}), "
            f"{done}/{planned} sub-word reads completed, {stable}/{INSTANCES} stable, "
            f"{reset_ok}/{RESET_COMPARED} reset, lane mismatches={lane_bad} "
            f"(non-OKAY RRESP {resp_bad}; first {first_bad or 'none'}); reserved bits OR="
            f"0x{self._reserved.get('subword', 0):x} (LINKED-ISSUE SF-009 / SF-001, logged only)",
        )

    async def _byte_leg(
        self,
        name: str,
        target: RdlReg,
        neighbour: RdlReg,
        preload: int | None,
        lanes: tuple[int, ...],
        value: int,
    ) -> tuple[int, list[str]]:
        width = target.width_bytes
        pre = await self._rd(f"{name}_PRE", target.addr, width)
        nb = await self._rd(f"{name}_NB_PRE", neighbour.addr, neighbour.width_bytes)
        image = pre
        if preload == PRELOAD_PRE:
            preload = pre
        if preload is not None:
            await self._wr(f"{name}_PRELOAD", target.addr, preload, width)
            image = preload
        compares = 0
        results = []
        for lane in lanes:
            await self._wr(f"{name}_L{lane}", target.addr + lane, value, 1)
            image = _lane_image(image, lane, value)
            got = await self._rd(f"{name}_L{lane}_RB", target.addr, width)
            nb_got = await self._rd(f"{name}_L{lane}_NB", neighbour.addr, neighbour.width_bytes)
            assert nb_got == nb, (
                f"{name}: neighbour {neighbour.path} read 0x{nb:x} before and 0x{nb_got:x} after "
                f"the lane-{lane} write"
            )
            compares += 1
            tag = "=" if got & target.declared_mask == image & target.declared_mask else "!="
            results.append(f"L{lane}:0x{got:x}{tag}img0x{image:x}")
        await self._wr(f"{name}_RESTORE", target.addr, pre, width)
        back = await self._rd(f"{name}_RESTORE_RB", target.addr, width)
        assert back == pre, (
            f"{name}: restore wrote 0x{pre:x} to {target.path}, read back 0x{back:x}"
        )
        return compares, results

    async def _byte_lane(self) -> None:
        # S3.
        legs = (
            (
                "SCRATCH0",
                rdl_register("smc_cpu_ctrl/SCRATCH[0]"),
                rdl_register("smc_cpu_ctrl/SCRATCH[1]"),
                0,
                (1, 3),
                0xA5,
            ),
            *(
                (
                    f"{bank.upper()}15_START",
                    rdl_register(f"smc_{bank}_filter_ctrl[15]/START_ADDR"),
                    rdl_register(f"smc_{bank}_filter_ctrl[15]/END_ADDR"),
                    PRELOAD_PRE,
                    (1, 3, 5),
                    0x5A,
                )
                for bank in ("inbound", "outbound")
            ),
            (
                "TIMER_CTRL",
                rdl_register("smc_system_timer_octs/CTRL"),
                rdl_register("smc_system_timer_octs/TIMER_PRESET_LO"),
                None,
                (1,),
                0x05,
            ),
            (
                "TELEM0_CTRL",
                rdl_register("smc_telemetry_receiver_wrap/telemetry_receiver[0]/CTRL"),
                rdl_register("smc_telemetry_receiver_wrap/telemetry_receiver[0]/INTR_ENABLE"),
                None,
                (1,),
                0x30,
            ),
        )
        restores = neighbours = 0
        results: list[str] = []
        for name, target, neighbour, preload, lanes, value in legs:
            n, res = await self._byte_leg(name, target, neighbour, preload, lanes, value)
            restores += 1
            neighbours += n
            results.append(f"{name}[{' '.join(res)}]")
        assert restores == 5 and neighbours == 10, f"restores {restores}, neighbours {neighbours}"
        self._mark("BYTE-LANE", neighbours)
        self._chk(
            "CHK-SWEEP-BYTE-LANE",
            f"5 targets, restores {restores}/5 exact, neighbours unchanged "
            f"{neighbours}/{neighbours}, lane results={'; '.join(results)} "
            "(LINKED-ISSUE SF-009 / SF-031, logged only)",
        )

    async def _fullwidth_remap(self) -> None:
        # S4.
        legs = (
            ("ALIAS7", "smc_alias_remap[7]/REGION/region_attrs", ALIAS_ATTRS_FIELDS),
            ("MMODE7", "smc_mmode_remap[7]/REGION/region_attrs", ORMP_FIELDS),
            ("XVISOR7", "smc_xvisor_remap[7]/REGION/region_attrs", ORMP_FIELDS),
        )
        ok = []
        zeroed = 0
        for name, path, fields in legs:
            addr = rdl_register(path).addr
            await self._wr(f"{name}_ONES", addr, ALL64)
            got = await self._rd(f"{name}_ONES_RB", addr)
            assert got & fields == fields, (
                f"{name} region_attrs read 0x{got:016x} after all ones; documented fields "
                f"0x{fields:016x} must all read 1"
            )
            self._note_reserved("remap", got, fields)
            await self._wr(f"{name}_ZERO", addr, 0)
            got = await self._rd(f"{name}_ZERO_RB", addr)
            assert got & fields == 0, f"{name} region_attrs read 0x{got:016x} after the zero write"
            self._note_reserved("remap-zero", got, fields)
            zeroed += 1
            ok.append(f"{name.lower()} attrs fields ok")
        self._mark("FULLWIDTH-REMAP", 4 * len(legs))
        self._chk(
            "CHK-SWEEP-FULLWIDTH-REMAP",
            f"{', '.join(ok)}, zeroed {zeroed}/3, reserved=ones:0x"
            f"{self._reserved.get('remap', 0):016x} zero:0x"
            f"{self._reserved.get('remap-zero', 0):016x} (LINKED-ISSUE SF-001 / SF-002, logged only)",
        )

    async def _window_reads(
        self, label: str, base: int, offsets: range, resp: int
    ) -> list[SmcSysAxiItem]:
        out: list[SmcSysAxiItem] = []
        offs = list(offsets)
        for k in range(0, len(offs), WINDOW_GROUP):
            chunk = [
                self._item(SmcSysAxiOp.READ, f"{label}_{o:03x}", base + o, 4, resp=resp)
                for o in offs[k : k + WINDOW_GROUP]
            ]
            await self._group(f"{label}_{offs[k]:03x}", chunk)
            for item in chunk:
                self._check_resp(item, resp)
            out.extend(chunk)
        return out

    async def _timer_window(self) -> None:
        # S5.
        first, last = generated_window("smc_system_timer_octs")
        assert first == 0xA000 and last - first + 1 == TIMER_APERTURE, (
            f"timer aperture 0x{first:x}-0x{last:x}"
        )
        assert generated_decoded_extent("smc_system_timer_octs") == TIMER_EXTENT
        base = LOCAL_BASE_RESET + first
        regs = await self._window_reads("TIMER", base, range(0, TIMER_EXTENT, 4), RESP_OKAY)
        assert len(regs) == 9
        for (name, want), item in zip(TIMER_REGS, regs):
            reg = rdl_register(f"smc_system_timer_octs/{name}")
            assert reg.addr == item.addr, f"{name} at 0x{reg.addr:x}, swept 0x{item.addr:x}"
            got = item.rdata
            if name == "STATUS":
                mode = 0 if self.is_primary else 1
                assert got & TIMER_STATUS_RUNNING == 0 and (got & TIMER_STATUS_MODE) == mode, (
                    f"timer STATUS reads 0x{got:08x}: RUNNING must be 0 and MODE "
                    f"NOT(is_primary={self.is_primary})={mode}"
                )
            else:
                assert got & reg.declared_mask == want, (
                    f"timer {name} reads 0x{got:08x}, documented reset 0x{want:08x}"
                )
            self._note_reserved("timer", got, reg.declared_mask)
        past = await self._window_reads(
            "TIMER_PAST", base, range(TIMER_EXTENT, TIMER_APERTURE, 4), RESP_DECERR
        )
        bad = [i for i in past if i.rdata != DEADSPACE_RDATA]
        assert not bad, (
            f"{len(bad)} past-extent timer reads returned data other than 0x{DEADSPACE_RDATA:X}: "
            + ", ".join(f"0x{i.addr:x}=0x{i.rdata:x}" for i in bad[:6])
        )
        assert len(past) == 1015, f"{len(past)} past-extent timer reads"
        self._mark("TIMER-WINDOW", len(regs) + len(past))
        self._chk(
            "CHK-SWEEP-TIMER-WINDOW",
            f"9/9 regs reset OKAY (MODE={int(not self.is_primary)} for "
            f"tb_chiplet_is_primary={self.is_primary}, reserved OR="
            f"0x{self._reserved.get('timer', 0):x} logged), "
            f"{len(past)}/1015 past-extent DECERR 0x{DEADSPACE_RDATA:X}",
        )

    async def _telem_window(self) -> None:
        # S6.
        first, last = generated_window("smc_telemetry_receiver_wrap")
        assert first == 0x9000 and last - first + 1 == TELEM_APERTURE, (
            f"telemetry aperture 0x{first:x}-0x{last:x}"
        )
        assert generated_decoded_extent("smc_telemetry_receiver_wrap") == TELEM_EXTENT
        base = LOCAL_BASE_RESET + first
        inside = await self._window_reads("TELEM", base, range(0, TELEM_EXTENT, 4), RESP_OKAY)
        nonzero = [(i.addr - base, i.rdata) for i in inside if i.rdata != 0]
        assert len(nonzero) == TELEM_INSTANCES and all(v == 1 for _o, v in nonzero), (
            f"telemetry in-extent nonzero words {[(hex(o), hex(v)) for o, v in nonzero]}; "
            f"exactly {TELEM_INSTANCES} must read 0x1"
        )
        past = await self._window_reads(
            "TELEM_PAST", base, range(TELEM_EXTENT, TELEM_APERTURE, 4), RESP_DECERR
        )
        bad = [i for i in past if i.rdata != DEADSPACE_RDATA]
        assert not bad, (
            f"{len(bad)} past-extent telemetry reads returned data other than "
            f"0x{DEADSPACE_RDATA:X}: " + ", ".join(f"0x{i.addr:x}=0x{i.rdata:x}" for i in bad[:6])
        )
        assert len(inside) == 192 and len(past) == 832, f"{len(inside)} / {len(past)} reads"
        await self._wr("CG_RESTORE", CLOCK_GATE_CONTROL, self.cg_saved)
        cg_back = await self._rd("CG_RESTORE_RB", CLOCK_GATE_CONTROL)
        self._mark("TELEM-WINDOW", len(inside) + len(past))
        self._chk(
            "CHK-SWEEP-TELEM-WINDOW",
            f"{len(inside)}/192 OKAY, nonzero={len(nonzero)} (=0x1) at "
            f"{','.join(f'+0x{o:x}' for o, _v in nonzero)} (LINKED-ISSUE SF-014, positions "
            f"logged), {len(past)}/832 DECERR 0x{DEADSPACE_RDATA:X}; CLOCK_GATE_CONTROL "
            f"restored 0x{self.cg_saved:x} read 0x{cg_back:x} (SF-030, logged)",
        )

    def _dbw(self, label: str, word: int) -> None:
        assert (word & F_DBW) >> 12 == F_DBW_VALUE, (
            f"{label}: FILTER_CONFIG 0x{word:016x} has data_bus_width "
            f"{(word & F_DBW) >> 12}, filter_ctrl.adoc gives 0x{F_DBW_VALUE:x} (R)"
        )

    async def _filter_lanes(self) -> None:
        # S7.
        restores = lane_ok = lane_total = pre_burst = rounded = unchanged = 0
        lane_bad: list[str] = []
        cleared: list[str] = []
        for e in self.entries:
            cfg = await self._rd(f"{e.name}_CFG_SAVE", e.cfg)
            start = await self._rd(f"{e.name}_START_SAVE", e.start)
            end = await self._rd(f"{e.name}_END_SAVE", e.end)
            assert not cfg & F_LOCKED, f"{e.name} FILTER_CONFIG 0x{cfg:016x} is locked before S7"
            self._dbw(f"{e.name} saved", cfg)
            same_page = start & ~PAGE_MASK == end & ~PAGE_MASK
            burst_pair = (start & ~PAGE_MASK, end | PAGE_MASK) if same_page else (start, end)
            image = cfg
            for k, (lane, value) in enumerate(FILTER_LANE_LEGS):
                data = _complement_with_lane(cfg, lane, value)
                await self._wr(f"{e.name}_LANE{k}", e.cfg, data, wstrb=1 << lane)
                image = _lane_image(image, lane, value)
                got = await self._rd(f"{e.name}_LANE{k}_RB", e.cfg)
                self._dbw(f"{e.name} lane leg {k}", got)
                lane_total += 1
                if got & F_RW == image & F_RW and not got & F_LOCKED:
                    lane_ok += 1
                elif len(lane_bad) < 6:
                    lane_bad.append(f"{e.name}#{k}:0x{got:x}/img0x{image:x}")
                pair = (
                    await self._rd(f"{e.name}_LANE{k}_START", e.start),
                    await self._rd(f"{e.name}_LANE{k}_END", e.end),
                )
                if k < BURST_SET_LEG:
                    assert pair == (start, end), (
                        f"{e.name} lane leg {k}: START/END 0x{pair[0]:x}/0x{pair[1]:x}, saved "
                        f"0x{start:x}/0x{end:x}; the allow_burst leg has not run yet"
                    )
                    pre_burst += 1 if k == BURST_SET_LEG - 1 else 0
                elif k == BURST_SET_LEG:
                    assert pair == burst_pair, (
                        f"{e.name} after allow_burst = 1: START/END 0x{pair[0]:x}/0x{pair[1]:x}; "
                        f"filter_ctrl.adoc:61-69 gives 0x{burst_pair[0]:x}/0x{burst_pair[1]:x} "
                        f"for saved 0x{start:x}/0x{end:x}"
                    )
                    if same_page:
                        rounded += 1
                    else:
                        unchanged += 1
                else:
                    cleared.append(f"{e.name}:0x{pair[0]:x}/0x{pair[1]:x}")
            for name, addr, word in (
                ("CFG", e.cfg, cfg),
                ("START", e.start, start),
                ("END", e.end, end),
                ("START2", e.start, start),
            ):
                await self._wr(f"{e.name}_{name}_RESTORE", addr, word)
            ref = (
                await self._rd(f"{e.name}_CFG_RESTORE_RB", e.cfg),
                await self._rd(f"{e.name}_START_RESTORE_RB", e.start),
                await self._rd(f"{e.name}_END_RESTORE_RB", e.end),
            )
            assert ref == (cfg, start, end), (
                f"{e.name}: restore wrote {tuple(hex(v) for v in (cfg, start, end))}, read back "
                f"{tuple(hex(v) for v in ref)}"
            )
            self._saved[e.name] = ref
            restores += 1
        assert restores == 32 and lane_total == 32 * len(FILTER_LANE_LEGS)
        assert pre_burst == 32 and rounded + unchanged == 32
        self._lane_summary = (lane_ok, lane_total, lane_bad)
        self._burst_summary = (pre_burst, rounded, unchanged, cleared)
        self._s7_restores = restores
        self._mark("FILTER-LANES", lane_total)

    async def _lock_unstrobed(self) -> None:
        # S8.
        restores = 0
        for e in self.entries:
            cfg = self._saved[e.name][0]
            await self._wr(f"{e.name}_UNSTROBED_LOCK", e.cfg, cfg | F_LOCKED, wstrb=0x7F)
            got = await self._rd(f"{e.name}_UNSTROBED_LOCK_RB", e.cfg)
            self._dbw(f"{e.name} unstrobed lock", got)
            locked = 1 if got & F_LOCKED else 0
            self._unstrobed_locked[e.name] = locked
            if not locked:
                await self._wr(f"{e.name}_UNSTROBED_RESTORE", e.cfg, cfg)
                back = await self._rd(f"{e.name}_UNSTROBED_RESTORE_RB", e.cfg)
                assert back == cfg, f"{e.name}: restore wrote 0x{cfg:016x}, read back 0x{back:016x}"
                self.branch_accesses += 2
                restores += 1
        self._mark("LOCK-UNSTROBED", len(self.entries))
        lane_ok, lane_total, lane_bad = self._lane_summary
        pre_burst, rounded, unchanged, cleared = self._burst_summary
        total = self._s7_restores + restores
        self._chk(
            "CHK-SWEEP-FCFG-LANES",
            f"{len(self.entries)}/32 entries, dbw=0x{F_DBW_VALUE:x} always, start/end pre-burst==saved "
            f"{pre_burst}/32, post-burst rounded={rounded} unchanged={unchanged} per "
            f"filter_ctrl.adoc:61-69, after allow_burst=0 start/end={' '.join(cleared[:4])}"
            f"{' ...' if len(cleared) > 4 else ''} (logged), restores exact {total}/{total}, "
            f"lane results={lane_ok}/{lane_total} match "
            f"the strobed-lane image (first mismatches {lane_bad or 'none'}), unstrobed-lock "
            f"locked={''.join(str(self._unstrobed_locked[e.name]) for e in self.entries)} "
            "(LINKED-ISSUE SF-009 / SF-029, logged only)",
        )

    def _entry(self, bank: str, idx: int) -> Entry:
        return next(e for e in self.entries if e.name == f"{bank}{idx}")

    def _expect_decerr(self, e: Entry) -> None:
        self.env.axi_monitor.expected_decerr_addrs.update((e.cfg, e.start, e.end))

    async def _fullwidth_filter(self) -> None:
        # S9.
        e = self._entry(*FULLWIDTH_ENTRY)
        assert not self._unstrobed_locked[e.name], f"{e.name} locked in S8; S9 needs it unlocked"
        await self._wr(f"{e.name}_ONES", e.cfg, ALL64)
        got = await self._rd(f"{e.name}_ONES_RB", e.cfg)
        want = {
            "locked": (F_LOCKED, 1),
            "allow_burst": (F_ALLOW_BURST, 1),
            "group_id": (F_GROUP_ID, 0xF),
            "src_id": (F_SRC_ID, 0xF),
            "data_bus_width": (F_DBW, F_DBW_VALUE),
            "allow_ns": (F_ALLOW_NS, 1),
            "entry_enabled": (F_ENTRY_EN, 1),
            "write_allowed": (F_WRITE, 1),
            "read_allowed": (F_READ, 1),
        }
        bad = {
            n: (got & m) >> ((m & -m).bit_length() - 1)
            for n, (m, v) in want.items()
            if (got & m) >> ((m & -m).bit_length() - 1) != v
        }
        assert not bad, f"{e.name} FILTER_CONFIG 0x{got:016x} after all ones: fields {bad}"
        self._note_reserved("fullwidth-filter", got, F_DECLARED)
        start = await self._rd(f"{e.name}_ONES_START", e.start)
        end = await self._rd(f"{e.name}_ONES_END", e.end)
        self._locked[e.name] = (got, start, end)
        self._expect_decerr(e)
        await self._wr(f"{e.name}_AFTER_LOCK", e.cfg, self._saved[e.name][0], resp=RESP_DECERR)
        self._mark("FULLWIDTH-FILTER", 5)
        self._chk(
            "CHK-SWEEP-FULLWIDTH-FILTER",
            f"out15 cfg fields all set (0x{got:016x}), dbw=0x{F_DBW_VALUE:x}, reserved="
            f"0x{self._reserved['fullwidth-filter']:016x} (LINKED-ISSUE SF-001, logged only), "
            f"START/END 0x{start:x}/0x{end:x}, next write DECERR",
        )

    async def _lock_set(self) -> None:
        # S10.
        skip = self._entry(*FULLWIDTH_ENTRY).name
        lane7 = fallback = matched = 0
        paths = []
        for e in self.entries:
            if e.name == skip:
                continue
            cfg, start, end = self._saved[e.name]
            data = (~cfg & ((1 << 56) - 1)) | ((((cfg >> 56) & 0xFF) | 0x80) << 56)
            await self._wr(f"{e.name}_LANE7_LOCK", e.cfg, data, wstrb=0x80)
            got = await self._rd(f"{e.name}_LANE7_LOCK_RB", e.cfg)
            if got & F_LOCKED:
                lane7 += 1
                paths.append("L")
            else:
                await self._wr(f"{e.name}_FALLBACK_LOCK", e.cfg, cfg | F_LOCKED)
                got = await self._rd(f"{e.name}_FALLBACK_LOCK_RB", e.cfg)
                self.branch_accesses += 2
                fallback += 1
                paths.append("F")
            s = await self._rd(f"{e.name}_LOCKED_START", e.start)
            n = await self._rd(f"{e.name}_LOCKED_END", e.end)
            assert got & F_LOCKED, f"{e.name} FILTER_CONFIG 0x{got:016x} is not locked"
            assert got & ~F_LOCKED == cfg & ~F_LOCKED and (s, n) == (start, end), (
                f"{e.name} locked config 0x{got:016x} START 0x{s:x} END 0x{n:x}; saved "
                f"0x{cfg:016x} / 0x{start:x} / 0x{end:x}"
            )
            matched += 1
            self._locked[e.name] = (got, s, n)
            self._expect_decerr(e)
        assert lane7 + fallback == 31 and matched == 31
        self._mark("LOCK-SET", matched)
        self._chk(
            "CHK-SWEEP-LOCK-SET",
            f"31/31 locked, config/start/end == S7 post-restore {matched}/31, lane7-path={lane7} "
            f"fallback={fallback} (per entry {''.join(paths)}; LINKED-ISSUE SF-009, logged)",
        )

    async def _locked_writes(self) -> None:
        # S11.
        writes = unchanged = locked = 0
        for e in self.entries:
            cfg, start, end = self._locked[e.name]
            legs = (
                ("CFG_L7_CLR", e.cfg, cfg & ~F_LOCKED, 0x80),
                ("CFG_L7_SET", e.cfg, cfg | F_LOCKED, 0x80),
                ("CFG_L0_INV", e.cfg, cfg ^ 0xFF, 0x01),
                ("START_INV", e.start, ~start & ALL64, None),
                ("END_INV", e.end, ~end & ALL64, None),
            )
            for name, addr, data, strb in legs:
                await self._wr(f"{e.name}_{name}", addr, data, wstrb=strb, resp=RESP_DECERR)
                writes += 1
            got = (
                await self._rd(f"{e.name}_LOCKED_CFG_RB", e.cfg),
                await self._rd(f"{e.name}_LOCKED_START_RB", e.start),
                await self._rd(f"{e.name}_LOCKED_END_RB", e.end),
            )
            assert got[0] & F_LOCKED, f"{e.name} lock cleared: FILTER_CONFIG 0x{got[0]:016x}"
            locked += 1
            assert got == (cfg, start, end), (
                f"{e.name}: locked values {tuple(hex(v) for v in (cfg, start, end))}, read "
                f"{tuple(hex(v) for v in got)} after the refused writes"
            )
            unchanged += 3
        assert writes == 160 and locked == 32 and unchanged == 96
        self._mark("LOCKED-WRITES", writes)
        self._chk(
            "CHK-SWEEP-LOCKED-DECERR",
            f"32 entries x 5 writes {writes}/160 DECERR, locked=1 {locked}/32, values unchanged "
            f"{unchanged}/96",
        )

    def _finish(self) -> None:
        # S12.
        bound = self.cfg.axi_timeout_ns
        waits = (
            ("fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last),
            (
                "sep_in_axi_access",
                f"{bound}ns per access",
                f"{self.accesses} done in {self.groups} pipelined groups and single accesses, "
                f"last {self._last}",
            ),
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{self.accesses + 1} bounded waits, "
            + " ".join(f"{n}=bound {b} last={s}" for n, b, s in waits)
            + "; expiry raises AssertionError in the driver or the wait, 0 expired",
        )
        assert tuple(t for t, _c, _s in self._stamps) == TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert tuple(self.chk_seen) == CHECKERS[:-1], f"checker order {self.chk_seen}"
        self._chk(
            "CHK-NONVAC",
            " < ".join(TERMS)
            + "; terms "
            + ", ".join(f"{t}(n={c})@{s}ns" for t, c, s in self._stamps)
            + f"; checker lines {','.join(self.chk_seen)}; SEP_IN accesses {self.accesses}",
        )
