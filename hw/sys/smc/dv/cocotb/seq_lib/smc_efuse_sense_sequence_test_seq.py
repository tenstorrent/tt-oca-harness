# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Automatic fuse sense sequence after a deliberate cold reset.

Sources: smu-smc.adoc (eFuse Interface), efuse_interface_ctrl.rdl.

A sampler records (rst_primary, cmd_valid, resp_valid, sense_done) on every clk_smc_i rising
edge; every check is made over that record, and every wait is a bounded count of edges.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

_STATUS = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR")
_SENSE_DONE_BM = _field_mask(
    _REPO / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_interface_ctrl.h",
    "EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_SENSE_DONE_bm",
)
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_NUM_WORDS = 256
_HOLD_SAMPLES = 8
_QUIET_WINDOW = 64
_POST_RISE_READS = 4
_HANDOVER_CYCLES = 2  # smu-smc.adoc lines 431-433: valid falls two cycles after the last strobe
_SENSE_BOUND_CYCLES = 200_000
_RESET_BOUND_CYCLES = 2_000
_RELEASE_BOUND_CYCLES = 20_000
_FIRST_REQUEST_BOUND_CYCLES = 200_000
_STROBE_BOUND_CYCLES = 200_000
_DONE_BOUND_CYCLES = 2_000
_READS_BOUND_CYCLES = 20_000
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
_CHK_STEP = {
    "CHK-SENSE-REQ-LATENCY": "S2",
    "CHK-SENSE-STROBE-COUNT": "S3",
    "CHK-SENSE-DONE-LOW": "S4",
    "CHK-SENSE-DONE-OFFSET": "S5",
    "CHK-SENSE-REQ-HANDOVER": "S6",
}


class smc_efuse_sense_sequence_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cold reset, then the cycle-accurate sense request, strobe stream and hand-over."""

    def __init__(self, name: str = "smc_efuse_sense_sequence_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.access_floor = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._rec: list[tuple[int, int, int, int]] = []
        self._reads: list[tuple[int, int, int]] = []
        self._stop_reads = False

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

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

    async def _status_stream(self) -> None:
        while not self._stop_reads:
            issue = len(self._rec)
            value = await self.csr_read("STATUS_STREAM", _STATUS, expected=None)
            complete = len(self._rec) - 1
            self._reads.append((issue, complete, int(value) & _SENSE_DONE_BM))

    # --- waits ----------------------------------------------------------
    async def _wait_find(self, name: str, bound: int, start: int, test) -> int:
        """First sampled edge at or after `start` where test(sample, edge) holds."""
        index = start
        waited = 0
        while True:
            while index < len(self._rec):
                if test(self._rec[index], index):
                    self._waits.append((name, bound, f"hit={index},last={self._last()}"))
                    return index
                index += 1
            if waited >= bound:
                raise AssertionError(
                    f"{name}: not satisfied within {bound} smc clocks; last={self._last()}"
                )
            waited += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            await NextTimeStep()

    async def _wait_edges(self, name: str, bound: int, count: int) -> None:
        await self._wait_find(name, bound, count - 1, lambda _t, _i: True)

    async def _wait_reads(self, name: str, bound: int, ready) -> None:
        waited = 0
        while not ready():
            if waited >= bound:
                raise AssertionError(
                    f"{name}: not satisfied within {bound} smc clocks; "
                    f"reads={self._reads[-6:]}; last={self._last()}"
                )
            waited += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            await NextTimeStep()
        self._waits.append((name, bound, f"reads={len(self._reads)},last={self._last()}"))

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"bringup_sense: {exc}") from exc
        self._waits.append(
            (
                "bringup_sense",
                _SENSE_BOUND_CYCLES,
                f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')}",
            )
        )
        sampler = cocotb.start_soon(self._sampler())
        stream = None
        try:
            await self._wait_edges("sampler_start", 16, 4)
            stream = await self._scenario()
        finally:
            sampler.cancel()
            if stream is not None and not stream.done():
                stream.cancel()

    async def _scenario(self):
        rec = self._rec
        reads = self._reads
        assert rec[-1][3] == 1, f"sense not done before the cold reset: {self._last()}"

        # S1
        assert_edge = len(rec)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        low = await self._wait_find(
            "reset_asserted", _RESET_BOUND_CYCLES, assert_edge, lambda t, _i: t[0] == 0
        )
        await self._wait_edges("reset_hold_samples", _RESET_BOUND_CYCLES, low + _HOLD_SAMPLES)
        held = rec[low : low + _HOLD_SAMPLES]
        assert all(t[0] == 0 and t[3] == 0 for t in held), (
            f"tb_fuse_sense_done or the primary reset moved under the held cold reset: {held}"
        )
        self._done("S1")

        # S2
        await self._send(SmcResetOp.COLD_RST_HI)
        stream = cocotb.start_soon(self._status_stream())
        await self._wait_released("cold release")
        rel = await self._wait_find(
            "reset_release", _RELEASE_BOUND_CYCLES, low, lambda t, _i: t[0] == 1
        )
        first = await self._wait_find(
            "first_request", _FIRST_REQUEST_BOUND_CYCLES, rel, lambda t, _i: t[1] == 1
        )
        first_strobe = await self._wait_find(
            "first_strobe", _STROBE_BOUND_CYCLES, first, lambda t, _i: t[2] == 1
        )
        rises = sum(1 for i in range(rel, first_strobe + 1) if rec[i][1] and not rec[i - 1][1])
        assert rises == 1, f"{rises} rising edges of cmd_valid before the first strobe"
        latency = first - rel
        self._done("S2")
        self._chk(
            "CHK-SENSE-REQ-LATENCY",
            "tb_efuse_shim_cmd_valid first read 1 %d clk_smc_i cycles after the first edge with "
            "rst_primary_smc_clk_no=1 (edge %d to %d; measured, no bound is asserted: owner value "
            "pending) with exactly %d rising edge before the first strobe at edge %d",
            latency,
            rel,
            first,
            rises,
            first_strobe,
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
        self._done("S5")
        self._chk(
            "CHK-SENSE-DONE-OFFSET",
            "tb_fuse_sense_done rose %d cycles after the 256th strobe (edge %d to %d; the "
            "port-visible offset is measured, owner value pending); "
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
            f"adoc states {_HANDOVER_CYCLES} (owner value pending); "
            f"rise of sense done at edge {rise}"
        )
        await self._wait_edges("quiet_window", _RESET_BOUND_CYCLES, fall + _QUIET_WINDOW)
        quiet = rec[fall : fall + _QUIET_WINDOW]
        assert len(quiet) == _QUIET_WINDOW, f"{len(quiet)} samples in the quiet window"
        assert all(t[1] == 0 and t[2] == 0 for t in quiet), (
            f"cmd_valid or resp_valid high inside the quiet window: {quiet}"
        )
        assert all(t[2] == 0 for t in rec[rise:]), "a strobe after the sense done"
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
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s as measured event edges, strict < between adjacent "
            "terms; SENSE_DONE@%d VALID_LOW@%d (shared edge allowed, owner value pending); "
            "checker lines %s; "
            "step stamps %s ps",
            " < ".join(f"{term}@{edge}" for term, edge in zip(_TERMS, edges)),
            edges[5],
            edges[6],
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
