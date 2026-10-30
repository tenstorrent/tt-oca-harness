# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded probes of every SMC component-map row's past-extent span, gap and outside cells.

Spec sources: memmap.adoc Address Space Organization; the generated component map
(regs/gen/adoc/memory_map.adoc, regs/gen/py/smc_memory_map.py) Past Extent column;
smc.rdl ocah_gap_resp; smc_base_config.rdl REGION_SIZE, LOCAL_BASE, GLOBAL_BASE,
CLOCK_GATE_CONTROL; filter_ctrl.rdl reset words.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _COMPONENT_ROWS,
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    CLOCK_GATE_CONTROL_RESET,
    GLOBAL_BASE_RESET,
    I2C_CG_EN,
    I3C_CG_EN,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_gap_decode_response_test_seq import GAP_RESP
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT,
    FILTER_CTRL_START_ADDR_REG_DEFAULT,
)

AXI_RESP_OKAY = 0
AXI_RESP_DECERR = 3
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}
WRITE_PATTERN = 0x5AA5_A55A_A5A5_5A5A
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
SIZES = (1, 2, 4, 8)
PORTS = ("SEP", "SYS")
ORDERS = ("RW", "WR")

GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
MMODE_OFFSET = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - LOCAL_BASE_RESET
XVISOR_OFFSET = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR") - LOCAL_BASE_RESET
REMAP_END_OFFSET = XVISOR_OFFSET + smc_addr("SMC_TOP_XVISOR_REGION_SIZE")
# The clock-gate enables of the windows memmap.adoc says answer SLVERR while gated.
GATED_WINDOW_ENABLES = (
    ("I2C", I2C_CG_EN),
    ("UART", UART_CG_EN),
    ("I3C", I3C_CG_EN),
    ("AVS", AVS_CG_EN),
    ("TELEMETRY", TELEMETRY_CG_EN),
)

# Row counts of the generated component map the walk is written against.
PAST_ROWS = 30
PAST_ROWS_INSIDE = 24
PAST_ROWS_BEYOND = (
    "smc_cluster_plic",
    "smc_cluster_clint",
    "smc_cluster_core0_beu",
    "smc_cluster_core1_beu",
    "smc_cluster_core2_beu",
    "smc_cluster_core3_beu",
)
GAPS_INSIDE = 6
GAPS_BEYOND = 1

# Step 2, the draw, takes no simulation time and is not stamped.
_STEPS = ("S1", "S3", "S4", "S5", "S6")
_CHECKERS = (
    ("CHK-MRR-GATE-CLEAR", "S1"),
    ("CHK-MRR-PAST-EXTENT", "S3"),
    ("CHK-MRR-GAP", "S4"),
    ("CHK-MRR-OUTSIDE-WINDOWS", "S5"),
)


def _unit(row: dict) -> str:
    return row["key"].rsplit(":", 1)[-1]


class _Cell:
    """One drawn probe point: a read and a write of ``size`` bytes at ``addr``."""

    def __init__(self, kind, name, addr, size, port, order, inside, compare_data):
        self.kind = kind
        self.name = name
        self.addr = addr
        self.size = size
        self.port = port
        self.order = order
        self.inside = inside
        self.compare_data = compare_data
        self.rresp: int | None = None
        self.rdata = 0
        self.bresp: int | None = None

    def drawn(self) -> str:
        return f"{self.name}@0x{self.addr:x}/{self.size}B/{self.port}/{self.order}"


class smc_map_row_response_matrix_test_seq(SmcCsrSeq):
    """Walk every past-extent row, every gap and every outside class with seeded points."""

    def __init__(self, name: str = "smc_map_row_response_matrix_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self.fuse_state = "not waited"
        self.walk_accesses = 0
        self.expected_walk = 0
        self.visited: dict[str, set[str]] = {"ROW": set(), "GAP": set(), "OUT": set()}
        self.row_cells: list[_Cell] = []
        self.gap_cells: list[_Cell] = []
        self.out_cells: list[_Cell] = []
        self.past_rows: list[dict] = []
        self.gaps: list[tuple[str, int, int, bool]] = []
        self.region_size = REGION_SIZE_RESET

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {"SEP": self.env.sys_axi_agent, "SYS": self.env.sys_in_axi_agent}[port]
        return agent.sequencer

    async def _access(self, cell: _Cell, op: SmcSysAxiOp, expect_decerr: bool) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{cell.port.lower()}_{cell.name}_{op.name}")
        item.op = op
        item.addr = cell.addr
        item.length = cell.size
        item.wdata = WRITE_PATTERN & ((1 << (8 * cell.size)) - 1)
        item.expected = None
        item.allow_error = True
        if expect_decerr:
            item.expect_error = True
            item.expected_resp = AXI_RESP_DECERR
        await _OneShot(item, f"{cell.port.lower()}_{cell.name}_{op.name}_os").start(
            self._sequencer(cell.port)
        )
        self.accesses += 1
        self.walk_accesses += 1
        assert item.resp_code is not None, f"{cell.drawn()} {op.name}: no response recorded"
        return item

    async def _probe(self, cell: _Cell, compare_resp: bool) -> None:
        """Read and write ``cell`` in its drawn order; record both answers."""
        self.env.axi_monitor.expected_decerr_addrs.add(cell.addr)
        ops = (
            (SmcSysAxiOp.READ, SmcSysAxiOp.WRITE)
            if cell.order == "RW"
            else (SmcSysAxiOp.WRITE, SmcSysAxiOp.READ)
        )
        for op in ops:
            item = await self._access(cell, op, compare_resp)
            if op == SmcSysAxiOp.READ:
                cell.rresp = item.resp_code
                cell.rdata = item.rdata & ((1 << (8 * cell.size)) - 1)
            else:
                cell.bresp = item.resp_code
        if compare_resp:
            assert cell.rresp == AXI_RESP_DECERR, (
                f"{cell.drawn()}: rresp {_RESP_NAMES[cell.rresp]}, want DECERR "
                f"(rdata 0x{cell.rdata:x}; drawn={cell.drawn()})"
            )
            assert cell.bresp == AXI_RESP_DECERR, (
                f"{cell.drawn()}: bresp {_RESP_NAMES[cell.bresp]}, want DECERR "
                f"(drawn={cell.drawn()})"
            )

    def _compare_data(self, cell: _Cell, want: int) -> None:
        assert cell.rdata == want, (
            f"{cell.drawn()}: rdata 0x{cell.rdata:08x}, want 0x{want:08x} (drawn={cell.drawn()})"
        )

    def _draw_point(self, first: int, last: int, size: int) -> int:
        """An address aligned to ``size`` with the whole access inside [first, last]."""
        lo = (first + size - 1) // size
        hi = (last + 1 - size) // size
        assert lo <= hi, f"no {size}-byte point in 0x{first:x}..0x{last:x}"
        addr = size * self.rng.randint(lo, hi)
        assert addr % size == 0 and first <= addr and addr + size - 1 <= last
        return addr

    # -- table ------------------------------------------------------------

    def _build_tables(self) -> None:
        window_end = LOCAL_BASE_RESET + self.region_size
        rows = sorted(_COMPONENT_ROWS, key=lambda r: r["base"])
        self.past_rows = [r for r in rows if r["past_response"] is not None]
        assert len(self.past_rows) == PAST_ROWS, (
            f"{len(self.past_rows)} rows state a Past Extent response, the walk expects {PAST_ROWS}"
        )
        beyond = [_unit(r) for r in self.past_rows if r["end"] >= window_end]
        assert tuple(beyond) == PAST_ROWS_BEYOND, f"rows beyond BASE + REGION_SIZE: {beyond}"
        inside = [r for r in self.past_rows if r["end"] < window_end]
        assert len(inside) == PAST_ROWS_INSIDE, f"{len(inside)} past-extent rows inside the window"
        for row in self.past_rows:
            past = row["past_response"]
            assert (past["rresp"], past["bresp"]) == ("DECERR", "DECERR"), (
                f"{_unit(row)}: Past Extent {past['text']}"
            )
            assert row["base"] + row["occupied_size"] <= row["end"], f"{_unit(row)}: no span"
        gaps = []
        for prev, nxt in zip(rows, rows[1:]):
            if nxt["base"] > prev["end"] + 1:
                first, last = prev["end"] + 1, nxt["base"] - 1
                name = f"GAP_{_unit(prev)}_{_unit(nxt)}"
                gaps.append((name, first, last, last < window_end))
        n_in = sum(1 for g in gaps if g[3])
        assert n_in == GAPS_INSIDE, f"{n_in} gaps inside the window, the walk expects {GAPS_INSIDE}"
        assert len(gaps) - n_in == GAPS_BEYOND, f"{len(gaps) - n_in} gaps beyond the window"
        assert all(g[1] >= window_end for g in gaps if not g[3]), "a gap straddles the window"
        beyond_gap = next(g for g in gaps if not g[3])
        assert beyond_gap[1] == LOCAL_BASE_RESET + REMAP_END_OFFSET, (
            f"gap beyond the window starts at 0x{beyond_gap[1]:x}, not after the Xvisor region"
        )
        self.gaps = gaps

    def _cell(self, kind, name, first, last, size, inside, port=None) -> _Cell:
        addr = self._draw_point(first, last, size)
        port = port if port is not None else self.rng.choice(PORTS)
        order = self.rng.choice(ORDERS)
        compare_data = inside and size == 4
        return _Cell(kind, name, addr, size, port, order, inside, compare_data)

    def _draw(self) -> str:
        for row in self.past_rows:
            first = row["base"] + row["occupied_size"]
            last = row["end"]
            unit = _unit(row)
            inside = unit not in PAST_ROWS_BEYOND
            pinned = self._cell("ROW", f"{unit}.4B", first, last, 4, inside)
            size = self.rng.choice(SIZES)
            drawn = self._cell("ROW", f"{unit}.{size}B", first, last, size, inside, pinned.port)
            self.row_cells += [pinned, drawn]
        for name, first, last, inside in self.gaps:
            pinned = self._cell("GAP", f"{name}.4B", first, last, 4, inside)
            size = self.rng.choice(SIZES)
            drawn = self._cell("GAP", f"{name}.{size}B", first, last, size, inside)
            self.gap_cells += [pinned, drawn]
        classes = (
            ("BELOW_BOTH", 0, GLOBAL_BASE_RESET - 1),
            ("BETWEEN", GLOBAL_BASE_RESET + REMAP_END_OFFSET, LOCAL_BASE_RESET - 1),
            ("ABOVE_BOTH", LOCAL_BASE_RESET + 0x1000_0000, (1 << 32) - 1),
            ("ABOVE_4GIB", 1 << 32, (1 << 56) - 1),
        )
        pinned_classes = (
            ("REGION_END_LOCAL", LOCAL_BASE_RESET + self.region_size),
            ("REGION_END_GLOBAL", GLOBAL_BASE_RESET + self.region_size),
            ("XVISOR_LOCAL", LOCAL_BASE_RESET + XVISOR_OFFSET),
            ("XVISOR_GLOBAL", GLOBAL_BASE_RESET + XVISOR_OFFSET),
        )
        assert self.region_size == MMODE_OFFSET, (
            f"REGION_SIZE 0x{self.region_size:x} is not the M-mode region offset "
            f"0x{MMODE_OFFSET:x}, so BASE + REGION_SIZE is not its first word"
        )
        for port in PORTS:
            for name, first, last in classes:
                size = self.rng.choice(SIZES)
                self.out_cells.append(self._cell("OUT", name, first, last, size, False, port))
            for name, addr in pinned_classes:
                size = self.rng.choice(SIZES)
                self.out_cells.append(
                    self._cell("OUT", name, addr, addr + size - 1, size, False, port)
                )
        for cells in (self.row_cells, self.gap_cells, self.out_cells):
            self.rng.shuffle(cells)
        self.expected_walk = 2 * (len(self.row_cells) + len(self.gap_cells) + len(self.out_cells))
        table = "; ".join(c.drawn() for c in self.row_cells + self.gap_cells + self.out_cells)
        cocotb.log.info("RAND-SEED: %d; RAND-DRAW: %s", self.seed, table)
        return table

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> str:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        bases = []
        for label, addr, want in (
            ("REGION_SIZE", REGION_SIZE_REG, REGION_SIZE_RESET),
            ("LOCAL_BASE", LOCAL_BASE_REG, LOCAL_BASE_RESET),
            ("GLOBAL_BASE", GLOBAL_BASE_REG, GLOBAL_BASE_RESET),
        ):
            got = await self.csr_read(label, addr, expected=want, length=8)
            assert got == want, f"{label} reads 0x{got:x}, reset 0x{want:x}"
            bases.append(f"{label}=0x{got:X}")
        self.region_size = REGION_SIZE_RESET
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        enables = []
        for name, mask in GATED_WINDOW_ENABLES:
            assert (cg & mask) == 0, (
                f"CLOCK_GATE_CONTROL 0x{cg:08x}: {name} enable set before the walk"
            )
            enables.append(f"{name}=0")
        for label, addr, value in (
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, PASS_ALL_END),
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"INBOUND0_{label}_PASS_ALL", addr, value, length=8)
        for label, addr, value in (
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, PASS_ALL_END),
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            got = await self.csr_read(f"INBOUND0_{label}_RB", addr, expected=value, length=8)
            assert got == value, f"inbound entry 0 {label} reads 0x{got:x}, wrote 0x{value:x}"
        probe = SmcSysAxiItem("sys_ADMIT_PROBE")
        probe.op = SmcSysAxiOp.READ
        probe.addr = LOCAL_BASE_RESET
        probe.length = 4
        probe.allow_error = True
        await _OneShot(probe, "sys_ADMIT_PROBE_os").start(self._sequencer("SYS"))
        self.accesses += 1
        assert probe.resp_code == AXI_RESP_OKAY, (
            f"SYS_IN read of 0x{LOCAL_BASE_RESET:08x} with entry 0 pass-all answered "
            f"{_RESP_NAMES[probe.resp_code]}, want OKAY"
        )
        self.cg_text = (
            f"CLOCK_GATE_CONTROL=0x{cg:08X} (reset 0x{CLOCK_GATE_CONTROL_RESET:08X}): "
            f"{', '.join(enables)}, so no compared cell lies in a gated window; "
            f"{', '.join(bases)} at their reset words; inbound entry 0 pass-all read back and "
            f"a SYS_IN read of 0x{LOCAL_BASE_RESET:08X} answered OKAY; {self.fuse_state}"
        )
        self._build_tables()
        return self.cg_text

    async def _s3_rows(self) -> str:
        parts = []
        printed = []
        for cell in self.row_cells:
            unit = cell.name.split(".", 1)[0]
            row = next(r for r in self.past_rows if _unit(r) == unit)
            if cell.inside and cell.size != 4:
                await self._probe(cell, compare_resp=False)
                printed.append(
                    f"{cell.drawn()} rresp={_RESP_NAMES[cell.rresp]} rdata=0x{cell.rdata:x} "
                    f"bresp={_RESP_NAMES[cell.bresp]}"
                )
            else:
                await self._probe(cell, compare_resp=True)
                if cell.compare_data:
                    self._compare_data(cell, row["past_response"]["rdata"])
                    parts.append(f"{cell.drawn()} DECERR/0x{cell.rdata:08X}/DECERR")
                else:
                    parts.append(f"{cell.drawn()} DECERR/DECERR rdata=0x{cell.rdata:x} printed")
            self.visited["ROW"].add(unit)
        assert len(self.visited["ROW"]) == PAST_ROWS, f"{len(self.visited['ROW'])} rows visited"
        return (
            f"{len(self.visited['ROW'])} rows visited ({PAST_ROWS_INSIDE} inside the window, "
            f"{len(PAST_ROWS_BEYOND)} beyond BASE + REGION_SIZE); compared drawn="
            + "; ".join(parts)
            + "; printed, not compared drawn="
            + ("; ".join(printed) if printed else "none")
        )

    async def _s4_gaps(self) -> str:
        parts = []
        for cell in self.gap_cells:
            await self._probe(cell, compare_resp=True)
            if cell.compare_data:
                self._compare_data(cell, GAP_RESP[1])
                parts.append(f"{cell.drawn()} DECERR/0x{cell.rdata:08X}/DECERR")
            else:
                where = "inside" if cell.inside else "beyond"
                parts.append(
                    f"{cell.drawn()} DECERR/DECERR ({where}) rdata=0x{cell.rdata:x} printed"
                )
            self.visited["GAP"].add(cell.name.rsplit(".", 1)[0])
        want = GAPS_INSIDE + GAPS_BEYOND
        assert len(self.visited["GAP"]) == want, f"{len(self.visited['GAP'])} gaps visited"
        return f"{want} gaps visited; drawn=" + "; ".join(parts)

    async def _s5_outside(self) -> str:
        parts = []
        for cell in self.out_cells:
            await self._probe(cell, compare_resp=True)
            parts.append(f"{cell.drawn()} DECERR/DECERR rdata=0x{cell.rdata:x} printed")
            self.visited["OUT"].add(f"{cell.name}:{cell.port}")
        assert len(self.visited["OUT"]) == 16, f"{len(self.visited['OUT'])} outside cells"
        return "8 outside classes on SEP_IN and SYS_IN all DECERR; drawn=" + "; ".join(parts)

    async def _s6_restore(self) -> None:
        for label, addr, want in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        ):
            await self.csr_write(f"INBOUND0_{label}_RESTORE", addr, want, length=8)
        for label, addr, want in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT),
            ("END", INBOUND0_END, FILTER_CTRL_END_ADDR_REG_DEFAULT),
            ("START", INBOUND0_START, FILTER_CTRL_START_ADDR_REG_DEFAULT),
        ):
            got = await self.csr_read(f"INBOUND0_{label}_RESTORE_RB", addr, expected=want, length=8)
            assert got == want, f"inbound entry 0 {label} reads 0x{got:x}, reset 0x{want:x}"
        assert self.walk_accesses == self.expected_walk, (
            f"walk issued {self.walk_accesses} accesses, drawn table holds {self.expected_walk}"
        )

    async def body(self) -> None:
        text = await self._s1()
        self._mark("S1")
        self._chk("CHK-MRR-GATE-CLEAR", text)

        self._draw()

        text = await self._s3_rows()
        self._mark("S3")
        self._chk("CHK-MRR-PAST-EXTENT", text)

        text = await self._s4_gaps()
        self._mark("S4")
        self._chk("CHK-MRR-GAP", text)

        text = await self._s5_outside()
        self._mark("S5")
        self._chk("CHK-MRR-OUTSIDE-WINDOWS", text)

        await self._s6_restore()
        self._mark("S6")

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: wait_fuse_sense_done sub-waits tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n each bounded %d clk_smc_i rises, last "
            "observed %s; %d AXI accesses each bounded by the driver timeout %d ns "
            "(allow_timeout False), all answered; no other wait",
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.accesses,
            self.cfg.axi_timeout_ns,
        )

    def nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        assert len(self.visited["ROW"]) == PAST_ROWS
        assert len(self.visited["GAP"]) == GAPS_INSIDE + GAPS_BEYOND
        assert len(self.visited["OUT"]) == 16
        assert self.walk_accesses == self.expected_walk
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SETUP<PAST_EXTENT<GAPS<OUTSIDE<RESTORE; checker "
            "lines %s; rows %d, gaps %d, outside cells %d visited; walk accesses %d == %d; "
            "stamps %s",
            ",".join(chk_ids),
            len(self.visited["ROW"]),
            len(self.visited["GAP"]),
            len(self.visited["OUT"]),
            self.walk_accesses,
            self.expected_walk,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
