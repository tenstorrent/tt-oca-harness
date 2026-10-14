# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS TIMER_COUNT delta against edge counts of clk_smc_i, clk_ref_i and clk_periph_i.

Spec: clk_rst.adoc (Timer and Debug Timebases), system_timer_octs architecture.adoc.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT  # noqa: E402

OCTS_TIMER_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
OCTS_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
OCTS_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
OCTS_COUNT_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR")
OCTS_PRESET_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_LO_BASE_ADDR")
OCTS_PRESET_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_PRESET_HI_BASE_ADDR")

_REPO = Path(__file__).resolve().parents[6]
_OCTS_H = _REPO / "hw" / "ip" / "system_timer_octs" / "regs" / "gen" / "c" / "system_timer_octs.h"


def _octs_field(symbol: str) -> int:
    for line in _OCTS_H.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] == symbol:
            return int(parts[2], 0)
    raise KeyError(f"{symbol} not in {_OCTS_H}")


CREDIT_VAL_BM = _octs_field("SYSTEM_TIMER_OCTS__CTRL__CREDIT_VAL_bm")
CREDIT_VAL_BP = _octs_field("SYSTEM_TIMER_OCTS__CTRL__CREDIT_VAL_bp")
STATUS_RUNNING_BM = _octs_field("SYSTEM_TIMER_OCTS__STATUS__RUNNING_bm")
STATUS_MODE_BM = _octs_field("SYSTEM_TIMER_OCTS__STATUS__MODE_bm")

WINDOW_EDGES = 4000
RUNNING_POLL_READS = 32
ACCESS_TIMEOUT_NS = 50_000
EDGE_TIMEOUT_NS = 100_000
MEASURE_EDGES = 64
RELOAD_MAX_CYCLES = 16
PRESET = (1 << 32) | 0x4000
OKAY = 0

FENCE_TERMS = (
    "FIRST_START_RUNNING",
    "COUNT_PAIR_0",
    "WINDOW_EDGES_COUNTED",
    "COUNT_PAIR_1",
    "CELL_REWINDOW",
    "PRESET_WRITTEN",
    "SECOND_START",
    "RELOAD_SAMPLE",
)
CLOCKS = ("smc", "ref", "periph")


class smc_octs_clk_rate_test_seq(SmcCsrSeq):
    """Measure the OCTS count delta of two windows and of the second-START reload."""

    def __init__(
        self,
        name: str,
        *,
        cell: str,
        rate_id: str,
        periods_ns: tuple[float, float, float],
    ) -> None:
        super().__init__(name)
        self.cell = cell
        self.rate_id = rate_id
        self.declared_ps = dict(zip(("ref", "smc", "periph"), (int(p * 1000) for p in periods_ns)))
        self.measured_ps: dict[str, float] = {}
        self.window_timeout_ns = int(2 * WINDOW_EDGES * periods_ns[1]) + 10_000
        self.fence: list[tuple[str, int]] = []
        self.events: list[str] = []
        self.edges = dict.fromkeys(CLOCKS, 0)
        self.stop = False
        self.last_resp: int | None = None
        self.last_status = "no STATUS read yet"
        self.last_count = "no count read yet"
        self.last_edge_state = "no edge wait yet"
        self.edge_waits = 0
        self.window_waits = 0
        self.poll_reads = 0

    def _mark(self, term: str) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now))
        self.events.append(term)
        cocotb.log.info("STEP %s: complete at %d ps", term, now)

    def _emit(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.events.append(chk_id)

    async def _count_edges(self, key: str, clk) -> None:
        while not self.stop:
            await RisingEdge(clk)
            self.edges[key] += 1

    def _snap(self) -> dict[str, int]:
        return dict(self.edges)

    async def _edge(self, clk_name: str, clk, idx: int) -> None:
        self.edge_waits += 1
        try:
            await with_timeout(RisingEdge(clk), EDGE_TIMEOUT_NS, "ns")
        except cocotb.result.SimTimeoutError:
            raise AssertionError(
                f"{clk_name} rising edge {idx} not seen within {EDGE_TIMEOUT_NS} ns; "
                f"last={self.last_edge_state}"
            ) from None
        self.last_edge_state = f"{clk_name} edge {idx} at {int(get_sim_time('ps'))} ps"

    async def _measure_periods(self) -> None:
        dut = cocotb.top
        for name, clk in (
            ("ref", dut.clk_ref_i),
            ("smc", dut.clk_smc_i),
            ("periph", dut.clk_periph_i),
        ):
            await self._edge(name, clk, 0)
            start = get_sim_time("ps")
            for idx in range(1, MEASURE_EDGES + 1):
                await self._edge(name, clk, idx)
            self.measured_ps[name] = (get_sim_time("ps") - start) / MEASURE_EDGES
        for name, want in self.declared_ps.items():
            got = self.measured_ps[name]
            assert got == want, (
                f"cell {self.cell}: {name} period measured {got} ps, expected {want} ps"
            )

    async def _access(self, label: str, op: SmcSysAxiOp, addr: int, data: int = 0) -> int:
        item = SmcSysAxiItem(f"{'rd' if op == SmcSysAxiOp.READ else 'wr'}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.timeout_ns = ACCESS_TIMEOUT_NS
        if op == SmcSysAxiOp.WRITE:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.last_resp = item.resp_code
        assert item.resp_code == OKAY, (
            f"{label} @ 0x{addr:08x}: response code {item.resp_code}, expected OKAY ({OKAY}); "
            f"last STATUS={self.last_status} last count={self.last_count}"
        )
        return item.rdata

    async def _read_count(self, label: str) -> tuple[int, dict[str, int], dict[str, int]]:
        issue = self._snap()
        lo = await self._access(f"{label}_LO", SmcSysAxiOp.READ, OCTS_COUNT_LO)
        hi = await self._access(f"{label}_HI", SmcSysAxiOp.READ, OCTS_COUNT_HI)
        done = self._snap()
        value = (hi << 32) | lo
        self.last_count = f"{label}=0x{value:x}"
        return value, issue, done

    async def _read_status(self, label: str) -> int:
        status = await self._access(label, SmcSysAxiOp.READ, OCTS_STATUS)
        self.last_status = f"{label}=0x{status:x}"
        return status

    async def _wait_window(self) -> None:
        self.window_waits += 1
        try:
            await with_timeout(
                ClockCycles(cocotb.top.clk_smc_i, WINDOW_EDGES), self.window_timeout_ns, "ns"
            )
        except cocotb.result.SimTimeoutError:
            raise AssertionError(
                f"{WINDOW_EDGES} clk_smc_i edges not seen within {self.window_timeout_ns} ns; "
                f"last STATUS={self.last_status} last count={self.last_count}"
            ) from None

    async def _window(
        self,
        label: str,
        c0: int,
        c0_issue: dict[str, int],
        c0_done: dict[str, int],
        gran: int,
    ) -> dict:
        await self._wait_window()
        self._mark("WINDOW_EDGES_COUNTED" if label == "W1" else f"{label}_EDGES_COUNTED")
        c1, c1_issue, c1_done = await self._read_count(f"{label}_C1")
        delta = c1 - c0
        e_lo = c1_issue["smc"] - c0_done["smc"]
        e_hi = c1_done["smc"] - c0_issue["smc"]
        other = {k: c1_done[k] - c0_issue[k] for k in ("ref", "periph")}
        assert e_lo - gran <= delta <= e_hi + gran, (
            f"{label}: OCTS TIMER_COUNT delta {delta} (0x{c0:x} -> 0x{c1:x}) outside the "
            f"clk_smc_i interval [{e_lo - gran}, {e_hi + gran}] (E_lo={e_lo} E_hi={e_hi} "
            f"granularity {gran}); ref edges {other['ref']} periph edges {other['periph']} "
            f"cell {self.cell}"
        )
        return {
            "c0": c0,
            "c1": c1,
            "delta": delta,
            "e_lo": e_lo,
            "e_hi": e_hi,
            "other": other,
            "c1_done": c1_done,
            "c1_issue": c1_issue,
        }

    def _discriminate(self, win: dict, gran: int) -> str:
        lo, hi = win["e_lo"] - gran, win["e_hi"] + gran
        notes = []
        for key in ("ref", "periph"):
            count = win["other"][key]
            if self.declared_ps[key] == self.declared_ps["smc"]:
                notes.append(f"{key} edges {count} (same period as clk_smc_i: not discriminating)")
                continue
            assert not lo <= count <= hi, (
                f"{key} edge count {count} lies inside the clk_smc_i interval [{lo}, {hi}]; "
                f"delta {win['delta']} does not tell clk_smc_i from clk_{key}_i"
            )
            notes.append(f"{key} edges {count} outside [{lo}, {hi}]")
        return "; ".join(notes)

    async def body(self) -> None:
        dut = cocotb.top
        for sig in ("clk_ref_i", "clk_smc_i", "clk_periph_i", "tb_chiplet_is_primary"):
            assert hasattr(dut, sig), f"{sig} not exported by tb_top"
        await self.wait_fuse_sense_done()
        assert dut.tb_chiplet_is_primary.value.is_resolvable, "tb_chiplet_is_primary is X/Z"
        assert int(dut.tb_chiplet_is_primary.value) == 1, "this bench must be the PRIMARY chiplet"
        await self._measure_periods()

        ctrl = await self._access("OCTS_CTRL", SmcSysAxiOp.READ, OCTS_CTRL)
        assert ctrl == SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT, (
            f"OCTS CTRL read 0x{ctrl:x}, reset value 0x{SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT:x}"
        )
        gran = (ctrl & CREDIT_VAL_BM) >> CREDIT_VAL_BP
        assert gran > 0, "CREDIT_VAL reads 0"
        cocotb.log.info(
            "count-latch rule owner value pending: tolerance is CREDIT_VAL granularity %d only",
            gran,
        )

        tasks = [
            cocotb.start_soon(self._count_edges("smc", dut.clk_smc_i)),
            cocotb.start_soon(self._count_edges("ref", dut.clk_ref_i)),
            cocotb.start_soon(self._count_edges("periph", dut.clk_periph_i)),
        ]
        try:
            await self._run(gran)
        finally:
            self.stop = True
            for task in tasks:
                task.cancel()

    async def _run(self, gran: int) -> None:
        await self._access("OCTS_START_1", SmcSysAxiOp.WRITE, OCTS_TIMER_START, 1)
        status = 0
        for _ in range(RUNNING_POLL_READS):
            self.poll_reads += 1
            status = await self._read_status("OCTS_STATUS_POLL")
            if status & STATUS_RUNNING_BM:
                break
        assert status & STATUS_RUNNING_BM, (
            f"OCTS STATUS.RUNNING never rose within {RUNNING_POLL_READS} reads "
            f"(STATUS=0x{status:x})"
        )
        assert (status & STATUS_MODE_BM) == 0, f"OCTS STATUS reports SECONDARY mode: 0x{status:x}"
        self._mark(FENCE_TERMS[0])

        c0, c0_issue, c0_done = await self._read_count("W1_C0")
        self._mark(FENCE_TERMS[1])
        win1 = await self._window("W1", c0, c0_issue, c0_done, gran)
        self._mark(FENCE_TERMS[3])
        note1 = self._discriminate(win1, gran)

        win2 = await self._window("W2", win1["c1"], win1["c1_issue"], win1["c1_done"], gran)
        self._mark(FENCE_TERMS[4])
        note2 = self._discriminate(win2, gran)
        self._emit(
            self.rate_id,
            f"cell={self.cell} periods_ps ref={self.measured_ps['ref']} "
            f"smc={self.measured_ps['smc']} periph={self.measured_ps['periph']}; CREDIT_VAL "
            f"granularity {gran}; "
            + "; ".join(
                f"{tag} c0=0x{w['c0']:x} c1=0x{w['c1']:x} delta={w['delta']} within "
                f"[{w['e_lo'] - gran}, {w['e_hi'] + gran}] (E_lo={w['e_lo']} E_hi={w['e_hi']}) "
                f"{note}"
                for tag, w, note in (("window1", win1, note1), ("window2", win2, note2))
            ),
        )

        await self._access("OCTS_PRESET_LO", SmcSysAxiOp.WRITE, OCTS_PRESET_LO, PRESET & 0xFFFFFFFF)
        await self._access("OCTS_PRESET_HI", SmcSysAxiOp.WRITE, OCTS_PRESET_HI, PRESET >> 32)
        self._mark(FENCE_TERMS[5])
        await self._access("OCTS_START_2", SmcSysAxiOp.WRITE, OCTS_TIMER_START, 1)
        status_mid = await self._read_status("OCTS_STATUS_MID")
        assert status_mid & STATUS_RUNNING_BM, f"RUNNING 0 before 2nd START: 0x{status_mid:x}"
        await self._access("OCTS_START_3", SmcSysAxiOp.WRITE, OCTS_TIMER_START, 1)
        write_done = self._snap()
        self._mark(FENCE_TERMS[6])
        c2, c2_issue, c2_done = await self._read_count("RELOAD_C2")
        self._mark(FENCE_TERMS[7])
        gap = c2_issue["smc"] - write_done["smc"]
        since = c2_done["smc"] - write_done["smc"]
        assert gap <= RELOAD_MAX_CYCLES, (
            f"c2 read issued {gap} clk_smc_i cycles after the second START write, "
            f"limit {RELOAD_MAX_CYCLES}"
        )
        assert c2 >= PRESET, f"c2 0x{c2:x} below preset 0x{PRESET:x}: counter did not reload"
        assert c2 <= PRESET + since + gran, (
            f"c2 0x{c2:x} above preset 0x{PRESET:x} + {since} clk_smc_i edges + {gran}"
        )
        status_end = await self._read_status("OCTS_STATUS_AFTER")
        assert status_end & STATUS_RUNNING_BM, f"STATUS.RUNNING cleared: 0x{status_end:x}"
        win3 = await self._window("W3", c2, c2_issue, c2_done, gran)
        self._emit(
            "CHK-OCTS-START-RELOAD",
            f"preset P=0x{PRESET:x}; c2=0x{c2:x} in [P, P+{since}+{gran}] "
            f"({gap} clk_smc_i cycles after the second START write); "
            f"STATUS before=0x{status_mid:x} after=0x{status_end:x} RUNNING=1; "
            f"window c2=0x{c2:x} c3=0x{win3['c1']:x} "
            f"delta={win3['delta']} within [{win3['e_lo'] - gran}, {win3['e_hi'] + gran}] "
            f"(E_lo={win3['e_lo']} E_hi={win3['e_hi']})",
        )

        waits = (
            f"SEP_IN_access={ACCESS_TIMEOUT_NS}ns last_resp={self.last_resp} "
            f"fail=AssertionError(access timeout or non-OKAY) accesses={self.accesses}",
            f"RUNNING_poll={RUNNING_POLL_READS}reads last={self.last_status} "
            f"fail=AssertionError(RUNNING never set) reads={self.poll_reads}",
            f"window={WINDOW_EDGES}clk_smc_i/{self.window_timeout_ns}ns last={self.last_count} "
            f"fail=AssertionError(window expiry) windows={self.window_waits}",
            f"input_clock_edge={EDGE_TIMEOUT_NS}ns last={self.last_edge_state} "
            f"fail=AssertionError(no edge) edge_waits={self.edge_waits}",
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %d bounded waits: %s", len(waits), " ".join(waits))
        self._finish_fence()

    def _finish_fence(self) -> None:
        order = [t for t, _ in self.fence]
        terms = list(FENCE_TERMS)
        assert [t for t in order if t in terms] == terms, f"fence order {order} != {terms}"
        times = [s for _, s in self.fence]
        for prev, cur, term in zip(times, times[1:], order[1:]):
            assert cur > prev, f"step {term} stamp {cur} ps is not after {prev} ps"
        ev = self.events
        assert ev.index(self.rate_id) > ev.index("CELL_REWINDOW"), "rate line before CELL_REWINDOW"
        assert ev.index("CHK-OCTS-START-RELOAD") > ev.index("RELOAD_SAMPLE"), (
            "reload line before RELOAD_SAMPLE"
        )
        assert ev.index(self.rate_id) < ev.index("CHK-OCTS-START-RELOAD"), "checker order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s, CHK-OCTS-START-RELOAD; stamps %s",
            " < ".join(terms),
            self.rate_id,
            ", ".join(f"{t}@{s}" for t, s in self.fence),
        )
