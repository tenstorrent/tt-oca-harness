# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register round trips on the SMC crossbar and the AVSBus window per clock cell.

Spec sources: hw/sys/smc/doc/clk_rst.adoc, smc_base_config.rdl, avsbus_controller.rdl.

HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD and AVS_CFG_0.MAX_RETRIES are written, read back and
restored at the cell's period triple. The default cell also reads the reset value, the
periph3 and ref8 cells repeat the SMC-side round trip, and the slowest_periph cell keeps
eight same-ID reads outstanding.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Event, First, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _SMC_BASE_CFG_H, HANG_DET_SYS_AXI_TIMEOUT, _field_mask
from .smc_avsbus_protocol_utils import AVS_CFG_0, MAX_RETRIES_BM, MAX_RETRIES_BP
from .smc_csr_seq_utils import SmcCsrSeq

THR_MASK = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_bm")
THR_RESET = _field_mask(_SMC_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_reset")
THR_PATTERN = 0xA5A5A
MAX_RETRIES_VALUE = 0x2A
MEASURE_EDGES = 64
EDGE_TIMEOUT_NS = 1_000
ACCESS_TIMEOUT_NS = 50_000
OKAY = 0
OUTSTANDING_READS = 8
READ_AXI_ID = 0x21
LANE_BYTES = 8
QUIET_CYCLES = 256

CELL_STEPS = {
    "default": ("S1", "S2", "S3"),
    "smc_slower": ("S1", "S3"),
    "smc_equal": ("S1", "S3"),
    "periph_slower": ("S1", "S3"),
    "periph3": ("S1", "S3", "S4"),
    "ref8": ("S1", "S3", "S4"),
    "slowest_periph": ("S1", "S3", "S5"),
}
# (fence term, step, checker printed once the term is stamped)
CELL_TERMS = {
    "S1": (("CELL_PERIODS_MEASURED", None),),
    "S2": (("RESET_ROUND_TRIPPED", "CHK-REGXBAR-RESET-RT"),),
    "S3": (
        ("SMC_SIDE_WRITTEN", None),
        ("AVS_SIDE_WRITTEN", None),
        ("BOTH_READ_BACK", "CHK-CLK-RELATION-ROUNDTRIP"),
    ),
    "S4": (("SMC_SIDE_REPEATED", "CHK-REGXBAR-PERIODS"),),
    "S5": (("OUTSTANDING_DRAINED", "CHK-CLK-RELATION-BACKPRESSURE"),),
}


class smc_clk_relation_regxbar_test_seq(SmcCsrSeq):
    """Written-value round trips on one SMC-side and one AVSBus register."""

    def __init__(self, name: str, cell: str, periods_ns: tuple[float, float, float]) -> None:
        super().__init__(name)
        self.cell = cell
        self.periods_ns = periods_ns
        self.periods_ps: dict[str, float] = {}
        self.terms: list[tuple[str, str, int]] = []
        self.chks: list[tuple[str, int]] = []
        self.last_resp: int | None = None
        self.edge_state = "no edge wait yet"
        self.edge_waits = 0
        self.group_state = "no outstanding group yet"
        self.wait_fuse_state = "not started"

    async def _next_edge(self, name: str, clk) -> None:
        self.edge_waits += 1
        result = await First(RisingEdge(clk), Timer(EDGE_TIMEOUT_NS, unit="ns"))
        self.edge_state = f"{name} edge at {int(get_sim_time('ps'))} ps"
        if not isinstance(result, RisingEdge):
            raise AssertionError(
                f"{name} clock gave no rising edge within {EDGE_TIMEOUT_NS} ns; "
                f"last state {self.edge_state}"
            )

    async def _measure_periods(self) -> None:
        """Mean period of each input clock over MEASURE_EDGES of its own rising edges."""
        dut = cocotb.top
        for name, clk in (
            ("ref", dut.clk_ref_i),
            ("smc", dut.clk_smc_i),
            ("periph", dut.clk_periph_i),
        ):
            await self._next_edge(name, clk)
            start = get_sim_time("ps")
            for _ in range(MEASURE_EDGES):
                await self._next_edge(name, clk)
            self.periods_ps[name] = (get_sim_time("ps") - start) / MEASURE_EDGES
        for name, declared in zip(("ref", "smc", "periph"), self.periods_ns):
            want = round(declared * 1000)
            got = self.periods_ps[name]
            assert abs(got - want) < 1, (
                f"cell {self.cell}: {name} period measured {got} ps over {MEASURE_EDGES} "
                f"edges, the cell requires {want} ps"
            )

    def _periods_text(self) -> str:
        return (
            f"ref={self.periods_ps['ref']:.0f}ps smc={self.periods_ps['smc']:.0f}ps "
            f"periph={self.periods_ps['periph']:.0f}ps"
        )

    def _term(self, step: str, term: str) -> None:
        now = int(get_sim_time("ps"))
        self.terms.append((term, step, now))
        cocotb.log.info("STEP %s: %s at %d ps", step, term, now)

    def _chk(self, chk_id: str, text: str) -> None:
        self.chks.append((chk_id, int(get_sim_time("ps"))))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _rd(self, label: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        item.timeout_ns = ACCESS_TIMEOUT_NS
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._check_resp(label, item)
        if expected is not None:
            assert item.rdata == expected, (
                f"{label} @ 0x{addr:08x}: read 0x{item.rdata:08x}, expected 0x{expected:08x}"
            )
        return item.rdata

    async def _wr(self, label: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.timeout_ns = ACCESS_TIMEOUT_NS
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._check_resp(label, item)

    def _check_resp(self, label: str, item: SmcSysAxiItem) -> None:
        self.last_resp = item.resp_code
        assert item.resp_code == OKAY, (
            f"{label} @ 0x{item.addr:08x}: response code {item.resp_code}, expected OKAY ({OKAY})"
        )

    @staticmethod
    def _avs_word(saved: int, retries: int) -> int:
        return (saved & ~MAX_RETRIES_BM) | (retries << MAX_RETRIES_BP)

    async def _smc_round_trip(self, label: str) -> tuple[int, int]:
        await self._wr(f"{label}_THR_WRITE", HANG_DET_SYS_AXI_TIMEOUT, THR_PATTERN)
        got = await self._rd(f"{label}_THR_READ", HANG_DET_SYS_AXI_TIMEOUT, THR_PATTERN & THR_MASK)
        await self._wr(f"{label}_THR_RESTORE", HANG_DET_SYS_AXI_TIMEOUT, THR_RESET)
        restored = await self._rd(
            f"{label}_THR_RESTORE_RB", HANG_DET_SYS_AXI_TIMEOUT, THR_RESET & THR_MASK
        )
        return got, restored

    async def _sample_axi(self, log: dict[str, list], stop: Event) -> None:
        """Record AR / R / B handshakes of the SEP_IN port on every clk_smc_i edge."""
        dut = cocotb.top
        names = (
            "arvalid",
            "arready",
            "rvalid",
            "rready",
            "rid",
            "rdata",
            "bvalid",
            "bready",
        )
        sigs = {n: getattr(dut, f"s_axi_{n}") for n in names}
        while not stop.is_set():
            await RisingEdge(dut.clk_smc_i)
            vals = {}
            for n, sig in sigs.items():
                assert sig.value.is_resolvable, f"s_axi_{n} is X/Z at {get_sim_time('ns')} ns"
                vals[n] = int(sig.value)
            now = int(get_sim_time("ns"))
            if vals["arvalid"] and vals["arready"]:
                log["ar"].append(now)
            if vals["rvalid"] and vals["rready"]:
                log["r"].append((now, vals["rid"], vals["rdata"]))
            if vals["bvalid"] and vals["bready"]:
                log["b"].append(now)

    def _member(self, label: str, op: SmcSysAxiOp, addr: int, wdata: int = 0, expected=None):
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = wdata
        item.expected = expected
        item.timeout_ns = ACCESS_TIMEOUT_NS
        return item

    async def _issue_group(self, name: str, items: list[SmcSysAxiItem]) -> None:
        group = SmcSysAxiGroupItem(name, items)
        await self.start_item(group)
        await self.finish_item(group)
        self.group_state = f"{name} collected at {int(get_sim_time('ns'))} ns"

    async def _outstanding(self, saved_avs: int) -> tuple[int, int, str]:
        avs_word = self._avs_word(saved_avs, MAX_RETRIES_VALUE)
        thr_word = THR_PATTERN & THR_MASK
        log: dict[str, list] = {"ar": [], "r": [], "b": []}
        stop = Event()
        sampler = cocotb.start_soon(self._sample_axi(log, stop))
        start = int(get_sim_time("ns"))
        writes = [
            self._member("OUT_THR_WRITE", SmcSysAxiOp.WRITE, HANG_DET_SYS_AXI_TIMEOUT, THR_PATTERN),
            self._member("OUT_AVS_WRITE", SmcSysAxiOp.WRITE, AVS_CFG_0, avs_word),
        ]
        self.group_state = f"2 writes issued at {start} ns"
        await self._issue_group("clk_relation_outstanding_writes", writes)
        reads = []
        for idx in range(OUTSTANDING_READS):
            if idx % 2 == 0:
                item = self._member(
                    f"OUT_THR_READ{idx}",
                    SmcSysAxiOp.READ,
                    HANG_DET_SYS_AXI_TIMEOUT,
                    expected=thr_word,
                )
            else:
                item = self._member(
                    f"OUT_AVS_READ{idx}", SmcSysAxiOp.READ, AVS_CFG_0, expected=avs_word
                )
            item.axi_id = READ_AXI_ID
            reads.append(item)
        read_start = int(get_sim_time("ns"))
        self.group_state = f"{len(reads)} same-ID reads issued at {read_start} ns"
        await self._issue_group("clk_relation_outstanding_reads", reads)
        elapsed = int(get_sim_time("ns")) - start
        await ClockCycles(cocotb.top.clk_smc_i, QUIET_CYCLES)
        stop.set()
        await sampler
        self.accesses += len(writes) + len(reads)
        self.group_state = f"10 responses collected in {elapsed} ns"
        assert elapsed <= ACCESS_TIMEOUT_NS, (
            f"outstanding group took {elapsed} ns, bound {ACCESS_TIMEOUT_NS} ns"
        )
        for item in writes + reads:
            self._check_resp(item.get_name(), item)
        assert len(log["b"]) == len(writes), f"B beats {log['b']}, expected {len(writes)}"
        assert len(log["r"]) == OUTSTANDING_READS, f"R beats {log['r']}, expected 8"
        assert len(log["ar"]) == OUTSTANDING_READS, f"AR handshakes {log['ar']}, expected 8"
        wanted = [item.expected for item in reads]
        for beat, (when, rid, rdata), item, want in zip(range(8), log["r"], reads, wanted):
            word = (rdata >> ((item.addr % LANE_BYTES) * 8)) & 0xFFFFFFFF
            assert rid == READ_AXI_ID, f"R beat {beat} at {when} ns: rid 0x{rid:x}"
            assert word == want, (
                f"R beat {beat} at {when} ns: word 0x{word:08x}, expected 0x{want:08x} "
                f"(issue order)"
            )
            assert item.rdata == want, f"{item.get_name()}: collected 0x{item.rdata:08x}"
        overlap = log["r"][0][0] > log["ar"][-1]
        detail = (
            f"reads issued at {read_start} ns, AR handshakes at {log['ar']} ns, first R beat at "
            f"{log['r'][0][0]} ns ({'after' if overlap else 'not after'} the last AR handshake), "
            f"R beats rid=0x{READ_AXI_ID:02x} x{len(log['r'])} at "
            f"{[t for t, _, _ in log['r']]} ns, B beats {len(log['b'])}, drain {elapsed} ns"
        )
        return elapsed, avs_word, detail

    def _assert_fence(self, steps: tuple[str, ...]) -> None:
        expected = [(t, s) for s in steps for t, _ in CELL_TERMS[s]]
        seen = [(t, s) for t, s, _ in self.terms]
        assert seen == expected, f"fence terms {seen} != {expected}"
        times = [ps for _, _, ps in self.terms]
        for prev, cur, (term, _s) in zip(times, times[1:], seen[1:]):
            assert cur > prev, f"fence term {term} stamp {cur} ps is not after {prev} ps"
        want_chks = [c for s in steps for _, c in CELL_TERMS[s] if c]
        assert [c for c, _ in self.chks] == want_chks, (
            f"checker lines {[c for c, _ in self.chks]} != {want_chks}"
        )
        stamp = {t: ps for t, _, ps in self.terms}
        by_chk = {c: t for s in steps for t, c in CELL_TERMS[s] if c}
        for chk_id, printed in self.chks:
            assert printed >= stamp[by_chk[chk_id]], (
                f"{chk_id} printed at {printed} ps before {by_chk[chk_id]} at "
                f"{stamp[by_chk[chk_id]]} ps"
            )

    async def body(self) -> None:
        assert self.cell in CELL_STEPS, f"unknown cell {self.cell}"
        steps = CELL_STEPS[self.cell]
        dut = cocotb.top
        for sig in ("clk_ref_i", "clk_smc_i", "clk_periph_i"):
            assert hasattr(dut, sig), f"{sig} not exported"

        self.wait_fuse_state = "waiting for fuse sense done (200000 clk_smc_i cycles)"
        await self.wait_fuse_sense_done()
        self.wait_fuse_state = "fuse sense done"
        await self._measure_periods()
        self._term("S1", "CELL_PERIODS_MEASURED")
        periods = self._periods_text()

        saved_thr_reset = None
        if "S2" in steps:
            saved_thr_reset = await self._rd(
                "THR_RESET", HANG_DET_SYS_AXI_TIMEOUT, THR_RESET & THR_MASK
            )
            wrote, restored = await self._smc_round_trip("S2")
            self._term("S2", "RESET_ROUND_TRIPPED")
            self._chk(
                "CHK-REGXBAR-RESET-RT",
                f"HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD reset read 0x{saved_thr_reset:05x} "
                f"(RDL reset 0x{THR_RESET:05x}), after write of 0x{THR_PATTERN:05x} read "
                f"0x{wrote:05x}, after restore read 0x{restored:05x}, all OKAY",
            )

        saved_thr = await self._rd("THR_SAVE", HANG_DET_SYS_AXI_TIMEOUT)
        saved_avs = await self._rd("AVS_CFG_0_SAVE", AVS_CFG_0)
        avs_word = self._avs_word(saved_avs, MAX_RETRIES_VALUE)
        assert avs_word != saved_avs, (
            f"AVS_CFG_0 already holds MAX_RETRIES 0x{MAX_RETRIES_VALUE:x}: 0x{saved_avs:08x}"
        )
        await self._wr("S3_THR_WRITE", HANG_DET_SYS_AXI_TIMEOUT, THR_PATTERN)
        self._term("S3", "SMC_SIDE_WRITTEN")
        await self._wr("S3_AVS_WRITE", AVS_CFG_0, avs_word)
        self._term("S3", "AVS_SIDE_WRITTEN")
        thr_rb = await self._rd("S3_THR_READ", HANG_DET_SYS_AXI_TIMEOUT, THR_PATTERN & THR_MASK)
        avs_rb = await self._rd("S3_AVS_READ", AVS_CFG_0, avs_word)
        await self._wr("S3_THR_RESTORE", HANG_DET_SYS_AXI_TIMEOUT, saved_thr)
        await self._wr("S3_AVS_RESTORE", AVS_CFG_0, saved_avs)
        thr_back = await self._rd("S3_THR_RESTORE_RB", HANG_DET_SYS_AXI_TIMEOUT, saved_thr)
        avs_back = await self._rd("S3_AVS_RESTORE_RB", AVS_CFG_0, saved_avs)
        self._term("S3", "BOTH_READ_BACK")
        self._chk(
            "CHK-CLK-RELATION-ROUNDTRIP",
            f"cell {self.cell} periods {periods}: HANG_DET threshold wrote 0x{THR_PATTERN:05x} "
            f"read 0x{thr_rb:05x}, restored 0x{thr_back:05x}; AVS_CFG_0 MAX_RETRIES "
            f"0x{MAX_RETRIES_VALUE:x} wrote 0x{avs_word:08x} read 0x{avs_rb:08x}, restored "
            f"0x{avs_back:08x}; all OKAY",
        )

        if "S4" in steps:
            wrote, restored = await self._smc_round_trip("S4")
            self._term("S4", "SMC_SIDE_REPEATED")
            self._chk(
                "CHK-REGXBAR-PERIODS",
                f"cell {self.cell} periods {periods}: HANG_DET threshold read 0x{wrote:05x} "
                f"after writing 0x{THR_PATTERN:05x} and 0x{restored:05x} after restore to "
                f"0x{THR_RESET:05x}, the values of the default-triple run",
            )

        if "S5" in steps:
            elapsed, out_word, detail = await self._outstanding(saved_avs)
            self._term("S5", "OUTSTANDING_DRAINED")
            self._chk(
                "CHK-CLK-RELATION-BACKPRESSURE",
                f"cell {self.cell} periods {periods}: 2 writes issued together, both B "
                f"responses taken, then {OUTSTANDING_READS} alternating reads under one AXI id "
                f"issued together; {detail}; all OKAY within {elapsed} ns (bound "
                f"{ACCESS_TIMEOUT_NS} ns, drain time printed, not specified, measured); "
                f"each read returned "
                f"0x{THR_PATTERN & THR_MASK:05x} or 0x{out_word:08x} in issue order",
            )
            await self._wr("S5_THR_RESTORE", HANG_DET_SYS_AXI_TIMEOUT, saved_thr)
            await self._wr("S5_AVS_RESTORE", AVS_CFG_0, saved_avs)
            await self._rd("S5_THR_RESTORE_RB", HANG_DET_SYS_AXI_TIMEOUT, saved_thr)
            await self._rd("S5_AVS_RESTORE_RB", AVS_CFG_0, saved_avs)

        waits = (
            f"fuse_sense={200_000}clk_smc_i last={self.wait_fuse_state} "
            f"fail=AssertionError(fuse sense timeout)",
            f"SEP_IN_access={ACCESS_TIMEOUT_NS}ns last_resp={self.last_resp} "
            f"fail=AssertionError(access timeout or non-OKAY) accesses={self.accesses}",
            f"clock_edge={EDGE_TIMEOUT_NS}ns last={self.edge_state} "
            f"fail=AssertionError(no edge) edge_waits={self.edge_waits}",
            f"outstanding_drain={ACCESS_TIMEOUT_NS}ns last={self.group_state} "
            f"fail=AssertionError(member timeout or elapsed over bound)",
        )
        cocotb.log.info("CHK-TIMEOUT-PATHS: %d bounded waits: %s", len(waits), " ".join(waits))

        self._assert_fence(steps)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(t for t, _, _ in self.terms),
            ", ".join(c for c, _ in self.chks),
            ", ".join(f"{t}@{ps}" for t, _, ps in self.terms),
        )
