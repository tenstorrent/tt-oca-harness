# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_011 ANCHOR: smc_efuse_sense_sequence_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: 105f1cdf375d81c7f7bb3ce5e131696ec9fde34e522301505090a3d3c177a711
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 467 `smc_efuse_sense_sequence_test` ENV: cocotb
"""Automatic fuse sense sequence after a deliberate cold reset.

Sources: smu-smc.adoc (eFuse Interface), efuse_interface_ctrl.rdl, efuse architecture.adoc
(shadow register subsystem; shadow access without waiting for fuse_sense_done).

A sampler records (rst_primary, cmd_valid, resp_valid, sense_done) on every clk_smc_i rising
edge; every check is made over that record, and every edge wait is a bounded count of edges.

One SMC_EFUSE_MAP shadow register R is read over SEP_IN three times: before the cold reset as
the reference, once by the STATUS stream after the first strobe while sense is still running, and
after the hand-over quiet window. R is the lowest-addressed map register whose first word is
non-zero in the image named by +smc_efuse_hex; that image word is the expected value, since the
shadow registers are loaded from the OTP at each boot (efuse architecture.adoc). The reference
read must equal it. The response and data of the read during sense are logged without a compare
(SF-030); the read after sense done must answer OKAY with the image word.

Every bounded wait is recorded with the bound in force, the expiry outcome and the last state
read from its own mechanism: the edge waits below, the reset agent's WAIT_STATE items and the
SEP_IN driver's per-item timeout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_addr_symbols, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import EFUSE_MAP_BASE, efuse_preload_words
from .smc_reset_seq_base import SmcResetSeqBase

_STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
_SENSE_DONE_BM = _field_mask(
    _REPO / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_interface_ctrl.h",
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_SENSE_DONE_bm",
)
_MAP_PREFIX = "SMC_TOP_SMC_EFUSE_MAP_"
_AXI_OKAY = 0
_STEPS = ("REFERENCE-READ", "S1", "S2", "PRESENSE-READ", "S3", "S4", "S5", "S6", "POSTSENSE-READ")
_NUM_WORDS = 256
_HOLD_SAMPLES = 8
_QUIET_WINDOW = 64
_POST_RISE_READS = 4
# doc/integrator/src/smu-smc.adoc, When valid falls: valid falls two cycles after the last strobe
_HANDOVER_CYCLES = 2
_SENSE_BOUND_CYCLES = 200_000
_RESET_BOUND_CYCLES = 2_000
_RELEASE_BOUND_CYCLES = 20_000
_FIRST_REQUEST_BOUND_CYCLES = 200_000
_STROBE_BOUND_CYCLES = 200_000
_DONE_BOUND_CYCLES = 2_000
_READS_BOUND_CYCLES = 20_000
_BRINGUP_SIGNALS = ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
_SIGNALS = (
    "rst_primary_smc_clk_no",
    "tb_efuse_shim_cmd_valid",
    "tb_efuse_shim_resp_valid",
    "tb_fuse_sense_done",
)
_TERMS = (
    "COLD_RESET_ASSERTED",
    "RELEASE",
    "FIRST_REQUEST",
    "FIRST_STROBE",
    "LAST_STROBE",
    "SENSE_DONE",
    "VALID_LOW",
    "HOLD_WINDOW_QUIET",
)
# (term, relation to the next term): "<" strict, "<=" the two may share an edge.
_CONTRACT_FENCE = (
    ("REFERENCE-READ", "<"),
    ("COLD-RESET", "<"),
    ("RELEASE", "<"),
    ("FIRST-STROBE", "<"),
    ("PRESENSE-READ", "<"),
    ("LAST-STROBE", "<"),
    ("SENSE-DONE", "<="),
    ("REQ-VALID-LOW", "<"),
    ("QUIET-WINDOW", "<"),
    ("POSTSENSE-READ", ""),
)
_CHK_STEP = {
    "CHK-SENSE-REQ-LATENCY": "S2",
    "CHK-SENSE-SHADOW-PRESENSE": "PRESENSE-READ",
    "CHK-SENSE-STROBE-COUNT": "S3",
    "CHK-SENSE-DONE-LOW": "S4",
    "CHK-SENSE-DONE-OFFSET": "S5",
    "CHK-SENSE-REQ-HANDOVER": "S6",
    "CHK-SENSE-SHADOW-POSTSENSE": "POSTSENSE-READ",
}


@dataclass
class _Wait:
    """One bounded wait as recorded from its mechanism."""

    name: str
    bound: int
    unit: str
    allow_timeout: bool | None
    timed_out: bool
    used: int
    last: str


def _efuse_map_registers() -> list[tuple[str, int]]:
    """Every SMC_EFUSE_MAP register (indexed ones expanded) as (name, address), by address."""
    regs = [
        (sym[len(_MAP_PREFIX) : -len("_BASE_ADDR")], smc_addr(sym))
        for sym in smc_addr_symbols(_MAP_PREFIX + r"\w+_BASE_ADDR")
    ]
    for sym in smc_addr_symbols(_MAP_PREFIX + r"\w+_NUM"):
        name = sym[len(_MAP_PREFIX) : -len("_NUM")]
        regs += [
            (f"{name}[{i}]", smc_indexed_addr(f"{_MAP_PREFIX}{name}_BASE_ADDR", i))
            for i in range(smc_addr(sym))
        ]
    return sorted(regs, key=lambda reg: reg[1])


class smc_efuse_sense_sequence_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cold reset, then the cycle-accurate sense request, strobe stream and hand-over."""

    def __init__(self, name: str = "smc_efuse_sense_sequence_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.access_floor = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[_Wait] = []
        self._rec: list[tuple[int, int, int, int]] = []
        self._rec_ps: list[int] = []
        self._reads: list[tuple[int, int, int]] = []
        self._stop_reads = False
        self._presense_armed = False
        self._target: tuple[str, int] | None = None
        self._shadow: dict[str, list[tuple[int, int, SmcSysAxiItem]]] = {}
        self._terms: list[tuple[str, int, int, int]] = []

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _term(self, term: str, edge: int, count: int) -> None:
        self._terms.append((term, edge, count, self._rec_ps[edge]))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _last(self) -> str:
        if not self._rec:
            return "no sample"
        rst, cmd, resp, done = self._rec[-1]
        return f"(edge={len(self._rec) - 1},rst={rst},cmd={cmd},resp={resp},done={done})"

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self._rec.append(tuple(self._sig(name) for name in _SIGNALS))
            self._rec_ps.append(int(get_sim_time("ps")))

    # --- SEP_IN reads ---------------------------------------------------
    async def _read(self, wait_name: str, addr: int, allow_error: bool) -> SmcSysAxiItem:
        """One SEP_IN read, bounded by the driver timeout in force for the item."""
        item = SmcSysAxiItem(f"rd_{wait_name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = allow_error
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._waits.append(
            _Wait(
                wait_name,
                item.timeout_ns or self.cfg.axi_timeout_ns,
                "ns",
                item.allow_timeout,
                item.timed_out,
                1,
                f"resp={item.resp_code},rdata=0x{item.rdata:08x},sampler={self._last()}",
            )
        )
        assert not item.timed_out, f"{wait_name}: {self._waits[-1]}"
        return item

    async def _shadow_read(self, tag: str, allow_error: bool) -> tuple[int, int, SmcSysAxiItem]:
        name, addr = self._target
        issue = len(self._rec)
        item = await self._read(f"{tag.lower()}_read_{name}", addr, allow_error)
        record = (issue, len(self._rec) - 1, item)
        self._shadow.setdefault(tag, []).append(record)
        return record

    async def _status_stream(self) -> None:
        while not self._stop_reads:
            if self._presense_armed and "PRE-SENSE" not in self._shadow:
                await self._shadow_read("PRE-SENSE", allow_error=True)
                continue
            issue = len(self._rec)
            item = await self._read(f"status_read[{len(self._reads)}]", _STATUS, False)
            complete = len(self._rec) - 1
            self._reads.append((issue, complete, int(item.rdata) & _SENSE_DONE_BM))

    # --- waits ----------------------------------------------------------
    def _expire(self, wait: _Wait, detail: str) -> None:
        wait.timed_out = True
        self._waits.append(wait)
        if not wait.allow_timeout:
            raise AssertionError(f"{wait.name}: {detail}; {wait}")

    async def _wait_level(self, name: str, bound: int) -> None:
        """Bounded wait for a testbench probe to read 1 on a clk_smc_i edge."""
        wait = _Wait(name, bound, "smc_clk", False, False, 0, "")
        while True:
            wait.last = f"{name}={self._sig(name)}"
            if self._sig(name) == 1:
                self._waits.append(wait)
                return
            if wait.used >= bound:
                self._expire(wait, "probe never read 1")
                return
            wait.used += 1
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _wait_find(self, name: str, bound: int, start: int, test) -> int:
        """First sampled edge at or after `start` where test(sample, edge) holds."""
        wait = _Wait(name, bound, "smc_clk", False, False, 0, "")
        index = start
        while True:
            while index < len(self._rec):
                if test(self._rec[index], index):
                    wait.last = f"hit={index},sampler={self._last()}"
                    self._waits.append(wait)
                    return index
                index += 1
            wait.last = f"scanned_to={index},sampler={self._last()}"
            if wait.used >= bound:
                self._expire(wait, "condition not met")
                return -1
            wait.used += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            await NextTimeStep()

    async def _wait_edges(self, name: str, bound: int, count: int) -> None:
        await self._wait_find(name, bound, count - 1, lambda _t, _i: True)

    async def _wait_until(self, name: str, bound: int, ready, state) -> None:
        """Bounded wait on a condition over the read record; `state` describes it."""
        wait = _Wait(name, bound, "smc_clk", False, False, 0, "")
        while True:
            wait.last = f"{state()},sampler={self._last()}"
            if ready():
                self._waits.append(wait)
                return
            if wait.used >= bound:
                self._expire(wait, "condition not met")
                return
            wait.used += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            await NextTimeStep()

    async def _wait_reads(self, name: str, bound: int, ready) -> None:
        await self._wait_until(
            name, bound, ready, lambda: f"reads={len(self._reads)},recent={self._reads[-3:]}"
        )

    async def _reset_wait(self, name: str, item_coro) -> None:
        """Record a reset agent WAIT_STATE item: bound, outcome and last sample from the item."""
        item = await item_coro
        self._waits.append(
            _Wait(
                name,
                item.timeout_ref_cycles,
                "ref_clk",
                None,
                item.timed_out,
                item.wait_ref_cycles,
                f"{item}",
            )
        )
        assert not item.timed_out, f"{name}: {self._waits[-1]}"

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        for name in _BRINGUP_SIGNALS:
            await self._wait_level(name, _SENSE_BOUND_CYCLES)
        sampler = cocotb.start_soon(self._sampler())
        stream = None
        try:
            await self._wait_edges("sampler_start", 16, 4)
            stream = await self._scenario()
        finally:
            sampler.cancel()
            if stream is not None and not stream.done():
                stream.cancel()

    def _select_target(self) -> tuple[str, int, int, str]:
        image = cocotb.plusargs.get("smc_efuse_hex")
        assert image is not None, "the run carries no +smc_efuse_hex fuse image"
        words = efuse_preload_words(Path(image))
        regs = _efuse_map_registers()
        for name, addr in regs:
            word = words[(addr - EFUSE_MAP_BASE) // 4]
            if word:
                return name, addr, word, image
        raise AssertionError(f"no SMC_EFUSE_MAP register of {len(regs)} is non-zero in {image}")

    async def _scenario(self):
        rec = self._rec
        reads = self._reads
        assert rec[-1][3] == 1, f"sense not done before the cold reset: {self._last()}"

        # Contract S1: select R from the fuse image, then read it as the reference.
        name, addr, image_word, image = self._select_target()
        self._target = (name, addr)
        cocotb.log.info(
            "STEP SMC_COV_B4_011.S1: R=%s@0x%08x selected as the lowest-addressed SMC_EFUSE_MAP "
            "register with a non-zero first word (image word 0x%08x, the expected value) in %s",
            name,
            addr,
            image_word,
            image,
        )
        _ri, ref_edge, ref_item = await self._shadow_read("REFERENCE", allow_error=False)
        assert ref_item.resp_code == _AXI_OKAY, (
            f"R={name} reference read answered resp={ref_item.resp_code}, expected OKAY"
        )
        assert rec[ref_edge][3] == 1, f"sense done 0 at the reference read edge {ref_edge}"
        reference = ref_item.rdata
        assert image_word != 0, f"R={name} image word is 0x0: the equality would be vacuous"
        assert reference == image_word, (
            f"R={name}@0x{addr:08x} reference read 0x{reference:08x}, image word 0x{image_word:08x}"
        )
        self._term("REFERENCE-READ", ref_edge, len(self._shadow["REFERENCE"]))
        self._done("REFERENCE-READ")

        # S1
        assert_edge = len(rec)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._reset_wait(
            "cold_assert_state",
            self._wait_state(
                "cold assert",
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=0,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
            ),
        )
        low = await self._wait_find(
            "reset_asserted", _RESET_BOUND_CYCLES, assert_edge, lambda t, _i: t[0] == 0
        )
        await self._wait_edges("reset_hold_samples", _RESET_BOUND_CYCLES, low + _HOLD_SAMPLES)
        held = rec[low : low + _HOLD_SAMPLES]
        assert all(t[0] == 0 and t[3] == 0 for t in held), (
            f"tb_fuse_sense_done or the primary reset moved under the held cold reset: {held}"
        )
        self._term("COLD-RESET", low, sum(1 for t in held if t[0] == 0))
        self._done("S1")

        # S2
        await self._send(SmcResetOp.COLD_RST_HI)
        stream = cocotb.start_soon(self._status_stream())
        await self._reset_wait("cold_release_state", self._wait_released("cold release"))
        rel = await self._wait_find(
            "reset_release", _RELEASE_BOUND_CYCLES, low, lambda t, _i: t[0] == 1
        )
        self._term(
            "RELEASE",
            rel,
            sum(1 for i in range(low + 1, rel + 1) if rec[i][0] and not rec[i - 1][0]),
        )
        first = await self._wait_find(
            "first_request", _FIRST_REQUEST_BOUND_CYCLES, rel, lambda t, _i: t[1] == 1
        )
        first_strobe = await self._wait_find(
            "first_strobe", _STROBE_BOUND_CYCLES, first, lambda t, _i: t[2] == 1
        )
        rises = sum(1 for i in range(rel, first_strobe + 1) if rec[i][1] and not rec[i - 1][1])
        assert rises == 1, f"{rises} rising edges of cmd_valid before the first strobe"
        self._term("FIRST-STROBE", first_strobe, sum(t[2] for t in rec[rel : first_strobe + 1]))
        latency = first - rel
        self._done("S2")
        self._chk(
            "CHK-SENSE-REQ-LATENCY",
            "tb_efuse_shim_cmd_valid first read 1 %d clk_smc_i cycles after the first edge with "
            "rst_primary_smc_clk_no=1 (edge %d to %d; not specified, measured, no bound is "
            "asserted) with exactly %d rising edge before the first strobe at edge %d",
            latency,
            rel,
            first,
            rises,
            first_strobe,
        )

        # Contract S3: the STATUS stream issues one read of R after the first strobe.
        self._presense_armed = True
        await self._wait_until(
            "presense_read_wait",
            _READS_BOUND_CYCLES,
            lambda: "PRE-SENSE" in self._shadow,
            lambda: f"presense_reads={len(self._shadow.get('PRE-SENSE', []))}",
        )
        pre_issue, pre_edge, pre_item = self._shadow["PRE-SENSE"][0]
        pre_k = sum(t[2] for t in rec[first_strobe:pre_issue])
        pre_done_now = self._sig("tb_fuse_sense_done")
        assert pre_k >= 1, f"R read issued at edge {pre_issue} before the first strobe"
        assert pre_item.resp_code is not None, (
            f"R read during sense returned no resolvable RRESP: {pre_item}"
        )
        assert rec[pre_edge][3] == 0 and pre_done_now == 0, (
            f"R read issued at strobe {pre_k} completed at edge {pre_edge} with "
            f"tb_fuse_sense_done sampled {rec[pre_edge][3]} (now {pre_done_now}): the read did "
            f"not overlap the sense"
        )
        self._term("PRESENSE-READ", pre_edge, pre_k)
        self._done("PRESENSE-READ")
        self._chk(
            "CHK-SENSE-SHADOW-PRESENSE",
            "R=%s@0x%08x, read issued at strobe %d/%d, completed at edge %d with sense_done=%d, "
            "RRESP=%d, RDATA=0x%08x (response and data measured, not compared: SF-030)",
            name,
            addr,
            pre_k,
            _NUM_WORDS,
            pre_edge,
            rec[pre_edge][3],
            pre_item.resp_code,
            pre_item.rdata,
        )

        # S3
        strobes: list[int] = []

        def count_strobes(t, i: int) -> bool:
            assert not t[3], f"tb_fuse_sense_done high at edge {i} after {len(strobes)} strobes"
            if t[2]:
                strobes.append(i)
            return len(strobes) == _NUM_WORDS

        last = await self._wait_find(
            "last_strobe", _STROBE_BOUND_CYCLES, first_strobe, count_strobes
        )
        rise = await self._wait_find(
            "sense_done", _DONE_BOUND_CYCLES, last, lambda t, _i: t[3] == 1
        )
        assert rise > last, f"tb_fuse_sense_done is 1 on the cycle of the last strobe: {rise}"
        before = sum(1 for t in rec[first_strobe:rise] if t[2])
        assert before == _NUM_WORDS, f"{before} strobes before the sense done, expected 256"
        gaps = [b - a for a, b in zip(strobes, strobes[1:])]
        self._term("LAST-STROBE", last, before)
        self._done("S3")
        self._chk(
            "CHK-SENSE-STROBE-COUNT",
            "%d resp_valid strobes from edge %d to edge %d before tb_fuse_sense_done rose at edge "
            "%d, sense done 0 on the 256th strobe cycle; strobe gap min %d max %d cycles "
            "(logged only)",
            before,
            first_strobe,
            last,
            rise,
            min(gaps),
            max(gaps),
        )

        # S4
        await self._wait_reads(
            "read_completed_after_rise",
            _READS_BOUND_CYCLES,
            lambda: any(c >= rise for _i, c, _v in reads),
        )
        assert all(t[3] == 0 for t in rec[low : last + 1]), (
            f"tb_fuse_sense_done read 1 between edge {low} and the last strobe at edge {last}"
        )
        early = [r for r in reads if r[1] < rise]
        mid = [r for r in early if first <= r[1] <= last]
        assert len(mid) >= 1, f"no STATUS read completed during the stream; reads={reads}"
        assert all(v == 0 for _i, _c, v in early), f"STATUS read 1 before the port rose: {early}"
        assert reads and reads[0][2] == 0, f"first STATUS read after the release: {reads[:1]}"
        self._done("S4")
        self._chk(
            "CHK-SENSE-DONE-LOW",
            "tb_fuse_sense_done 0 on every sampled edge from edge %d (cold reset asserted) to the "
            "last strobe at edge %d; %d STATUS reads completed before the port rise at edge %d, "
            "%d of them during the stream, all efuse_sense_done=0",
            low,
            last,
            len(early),
            rise,
            len(mid),
        )

        # S5
        offset = rise - last
        assert offset >= 1, f"tb_fuse_sense_done rose {offset} cycles after the last strobe"
        await self._wait_reads(
            "post_rise_reads",
            _READS_BOUND_CYCLES,
            lambda: sum(1 for issue, _c, _v in reads if issue > rise) >= _POST_RISE_READS,
        )
        self._stop_reads = True
        await stream
        late = [r for r in reads if r[0] > rise]
        assert len(late) >= _POST_RISE_READS, f"only {len(late)} reads issued after the rise"
        assert all(v == 1 for _i, _c, v in late), f"STATUS read 0 after the port rise: {late}"
        straddle = [r for r in reads if r[0] <= rise <= r[1]]
        self._term("SENSE-DONE", rise, sum(1 for _i, _c, v in late if v == 1))
        self._done("S5")
        self._chk(
            "CHK-SENSE-DONE-OFFSET",
            "tb_fuse_sense_done rose %d cycles after the 256th strobe (edge %d to %d; the "
            "port-visible offset is not specified, measured); "
            "the first STATUS read issued after "
            "the rise (edge %d) read efuse_sense_done=1 and %d reads issued after the rise all "
            "read 1; %d reads straddling the rise read %s",
            offset,
            last,
            rise,
            late[0][0],
            len(late),
            len(straddle),
            [v for _i, _c, v in straddle],
        )

        # S6
        fall = await self._wait_find(
            "valid_low", _DONE_BOUND_CYCLES, last + 1, lambda t, _i: t[1] == 0
        )
        assert fall - last == _HANDOVER_CYCLES, (
            f"cmd_valid fell {fall - last} cycles after the last strobe at edge {last}, the "
            f"adoc states {_HANDOVER_CYCLES}; "
            f"rise of sense done at edge {rise}"
        )
        await self._wait_edges("quiet_window", _RESET_BOUND_CYCLES, fall + _QUIET_WINDOW)
        quiet = rec[fall : fall + _QUIET_WINDOW]
        assert len(quiet) == _QUIET_WINDOW, f"{len(quiet)} samples in the quiet window"
        assert all(t[1] == 0 and t[2] == 0 for t in quiet), (
            f"cmd_valid or resp_valid high inside the quiet window: {quiet}"
        )
        assert all(t[2] == 0 for t in rec[rise:]), "a strobe after the sense done"
        self._term("REQ-VALID-LOW", fall, fall - last)
        self._term("QUIET-WINDOW", fall + _QUIET_WINDOW - 1, len(quiet))
        await self._wait_edges("s6_after_s5", _RESET_BOUND_CYCLES, len(rec) + 1)
        self._done("S6")
        self._chk(
            "CHK-SENSE-REQ-HANDOVER",
            "tb_efuse_shim_cmd_valid fell %d cycles after the last strobe (edge %d to %d) and "
            "read 0 on each of the %d edges quiet_window=[%d, %d] with the STATUS stream stopped "
            "and no firmware command issued; no strobe after the sense done",
            fall - last,
            last,
            fall,
            _QUIET_WINDOW,
            fall,
            fall + _QUIET_WINDOW - 1,
        )

        # Contract S4: R again, after STATUS read 1 and the quiet window.
        _pi, post_edge, post_item = await self._shadow_read("POSTSENSE", allow_error=False)
        assert post_item.resp_code == _AXI_OKAY, (
            f"R={name} read after sense done answered resp={post_item.resp_code}, expected OKAY"
        )
        assert post_item.rdata == image_word, (
            f"R={name} read after sense done 0x{post_item.rdata:08x}, image word 0x{image_word:08x}"
        )
        self._term("POSTSENSE-READ", post_edge, len(self._shadow["POSTSENSE"]))
        self._done("POSTSENSE-READ")
        self._chk(
            "CHK-SENSE-SHADOW-POSTSENSE",
            "R=%s@0x%08x image word=0x%08x (non-zero) reference=0x%08x == image word; post-sense "
            "RRESP=OKAY RDATA=0x%08x == image word (reference edge %d, sense done edge %d, "
            "post-sense edge %d)",
            name,
            addr,
            image_word,
            reference,
            post_item.rdata,
            ref_edge,
            rise,
            post_edge,
        )
        self.access_floor = len(reads)
        self._finish((low, rel, first, first_strobe, last, rise, fall, fall + _QUIET_WINDOW - 1))
        return stream

    def _finish(self, edges: tuple[int, ...]) -> None:
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        for i, (a, b) in enumerate(zip(edges, edges[1:])):
            ok = a <= b if i == 5 else a < b
            assert ok, f"fence {_TERMS[i]}@{a} !< {_TERMS[i + 1]}@{b}: {edges}"
        assert edges[6] - edges[4] == _HANDOVER_CYCLES and edges[5] - edges[4] >= 1, (
            f"port offsets: sense done edge {edges[5]}, valid low edge {edges[6]}"
        )
        terms = self._terms
        names = [t[0] for t in terms]
        assert names == [f[0] for f in _CONTRACT_FENCE], f"contract fence terms {names}"
        assert all(n >= 1 for _t, _e, n, _p in terms), f"zero-count term: {terms}"
        for (ta, ea, _na, _pa), (tb, eb, _nb, _pb), (_f, rel) in zip(
            terms, terms[1:], _CONTRACT_FENCE
        ):
            assert ea < eb or (rel == "<=" and ea == eb), (
                f"contract fence {ta}@{ea} !{rel} {tb}@{eb}"
            )
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s as measured event edges, strict < between adjacent "
            "terms; SENSE_DONE@%d VALID_LOW@%d (shared edge allowed; not specified, measured); "
            "checker lines %s; "
            "step stamps %s ps; contract fence by event edge %s",
            " < ".join(f"{term}@{edge}" for term, edge in zip(_TERMS, edges)),
            edges[5],
            edges[6],
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
            " ".join(
                f"{term}(edge={edge} t={ps}ps n={count}) {rel}"
                for (term, edge, count, ps), (_f, rel) in zip(terms, _CONTRACT_FENCE)
            ).strip(),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, %d expired; %s",
            len(self._waits),
            sum(1 for w in self._waits if w.timed_out),
            "; ".join(
                f"{w.name}: bound={w.bound} {w.unit}"
                + ("" if w.allow_timeout is None else f" allow_timeout={w.allow_timeout}")
                + f" timed_out={w.timed_out} used={w.used} last={w.last}"
                for w in self._waits
            ),
        )
