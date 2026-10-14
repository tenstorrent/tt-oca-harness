# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Delayed fuse reset gating on fuse sense done and ext_boot_seq_done_i.

Sources: port_table.adoc, clk_rst.adoc, smu-smc.adoc (eFuse Interface).

A sampler records (rst_primary, sense_done, fuse_reset_n, rst_warm, ext_boot) on every
clk_smc_i rising edge; every check is made over that record, and every wait is a bounded
count of edges. Requires +smc_hold_ext_boot.
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
_PIPE_STAGES = 16
_HOLD_SAMPLES = 8
_WINDOW_EDGES = 64
_REARM_QUIET_EDGES = 32
_SENSE_BOUND_CYCLES = 200_000
_RESET_BOUND_CYCLES = 2_000
_RELEASE_BOUND_CYCLES = 20_000
_FRST_RISE_BOUND_CYCLES = 2_000
_BOOT_RISE_BOUND_CYCLES = 16
_REARM_BOUND_CYCLES = 256
_READS_BOUND_CYCLES = 20_000
_RST, _SENSE, _FRST, _WARM, _EXT = range(5)
_TERMS = (
    "COLD_ASSERT",
    "SENSE_DONE_BOOT_LOW",
    "BOOT_RISE",
    "FRST_RELEASE",
    "EARLY_BOOT_RUN",
    "BOOT_DROP_OBSERVED",
    "SECOND_COLD",
    "SECOND_RELEASE",
)
_CHK_STEP = {
    "CHK-FRST-HELD-LOW": "S2",
    "CHK-FRST-16-STAGE": "S3",
    "CHK-FRST-EARLY-BOOT": "S4",
    "CHK-FRST-BOOT-DROP": "S5",
    "CHK-FRST-COLD-REARM": "S6",
}


class smc_efuse_fuse_reset_gate_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Boot gate and cold reset against the 16-stage delayed fuse reset."""

    def __init__(self, name: str = "smc_efuse_fuse_reset_gate_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.access_floor = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._rec: list[tuple[int, int, int, int, int]] = []
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

    def _ext_boot(self) -> int:
        if hasattr(cocotb.top, "ext_boot_seq_done"):
            return self._sig("ext_boot_seq_done")
        return 1 - self._sig("tb_hold_ext_boot")

    def _last(self) -> str:
        if not self._rec:
            return "no sample"
        rst, sense, frst, warm, ext = self._rec[-1]
        return (
            f"(edge={len(self._rec) - 1},rst={rst},sense={sense},frst={frst},warm={warm},ext={ext})"
        )

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self._rec.append(
                (
                    self._sig("rst_primary_smc_clk_no"),
                    self._sig("tb_fuse_sense_done"),
                    self._sig("tb_fuse_reset_n"),
                    self._sig("tb_rst_warm_smc_clk_n"),
                    self._ext_boot(),
                )
            )

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

    def _all(self, lo: int, hi: int, col: int, value: int) -> bool:
        return all(t[col] == value for t in self._rec[lo:hi])

    async def _cold_reset_low(self, tag: str) -> tuple[int, int]:
        assert_edge = len(self._rec)
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
            f"{tag}_reset_asserted",
            _RESET_BOUND_CYCLES,
            assert_edge,
            lambda t, _i: t[_RST] == 0,
        )
        return assert_edge, low

    async def _cold_reset_high(self, tag: str, low: int) -> int:
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("cold release")
        return await self._wait_find(
            f"{tag}_reset_release", _RELEASE_BOUND_CYCLES, low, lambda t, _i: t[_RST] == 1
        )

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        for name in ("tb_hold_ext_boot", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        assert self._sig("tb_hold_ext_boot") == 1, (
            "+smc_hold_ext_boot required so ext_boot_seq_done stays 0 from t=0"
        )
        for waited in range(_SENSE_BOUND_CYCLES + 1):
            if self._sig("tb_fuse_sense_done"):
                break
            if waited == _SENSE_BOUND_CYCLES:
                raise AssertionError(
                    f"bringup_sense: tb_fuse_sense_done not 1 within {_SENSE_BOUND_CYCLES} smc "
                    f"clocks; tb_fuse_reset_n={self._sig('tb_fuse_reset_n')}"
                )
            await RisingEdge(dut.clk_smc_i)
        self._waits.append(
            (
                "bringup_sense",
                _SENSE_BOUND_CYCLES,
                f"tb_fuse_sense_done=1,tb_fuse_reset_n={self._sig('tb_fuse_reset_n')}",
            )
        )
        sampler = cocotb.start_soon(self._sampler())
        stream = None
        try:
            stream = await self._scenario()
        finally:
            sampler.cancel()
            self._stop_reads = True
            if stream is not None and not stream.done():
                stream.cancel()

    async def _scenario(self):
        dut = cocotb.top
        rec = self._rec
        reads = self._reads

        # S1
        await self._wait_edges("hold_samples", _RESET_BOUND_CYCLES, _HOLD_SAMPLES)
        assert self._all(0, _HOLD_SAMPLES, _FRST, 0) and self._all(0, _HOLD_SAMPLES, _EXT, 0), (
            f"fuse_reset_n or ext_boot high under the held boot gate: {rec[:_HOLD_SAMPLES]}"
        )
        assert rec[-1][_SENSE] == 1, f"sense not done before the cold reset: {self._last()}"
        self._done("S1")

        # S2
        a_cold, low = await self._cold_reset_low("cold1")
        rel = await self._cold_reset_high("cold1", low)
        stream = cocotb.start_soon(self._status_stream())
        sense = await self._wait_find(
            "sense_boot_low", _SENSE_BOUND_CYCLES, rel, lambda t, _i: t[_SENSE] == 1
        )
        window_end = sense + _WINDOW_EDGES
        await self._wait_edges("held_window", _RESET_BOUND_CYCLES, window_end + 1)
        assert self._all(a_cold, window_end + 1, _FRST, 0), (
            f"fuse_reset_n rose with ext_boot low between edge {a_cold} and {window_end}: "
            f"{rec[a_cold : window_end + 1]}"
        )
        assert self._all(a_cold, window_end + 1, _EXT, 0), "ext_boot rose inside the window"
        await self._wait_reads(
            "status_reads_one",
            _READS_BOUND_CYCLES,
            lambda: any(v == 1 for _i, _c, v in reads),
        )
        first_one = next(k for k, r in enumerate(reads) if r[2] == 1)
        self._stop_reads = True
        await stream
        after = reads[first_one:]
        assert all(v == 1 for _i, _c, v in after), f"STATUS read 0 after a read of 1: {reads}"
        self._done("S2")
        self._chk(
            "CHK-FRST-HELD-LOW",
            "tb_fuse_reset_n 0 on every sampled edge from the cold reset assertion (edge %d) "
            "through sense done at edge %d and the following %d edges to edge %d with "
            "tb_hold_ext_boot=1 (ext_boot 0); %d bringup edges with the gate held read 0; "
            "STATUS.efuse_sense_done first read 1 at read %d of %d (edge %d) and %d later "
            "reads all 1",
            a_cold,
            sense,
            _WINDOW_EDGES,
            window_end,
            _HOLD_SAMPLES,
            first_one,
            len(reads),
            reads[first_one][0],
            len(after) - 1,
        )

        # S3
        write = len(rec)
        dut.tb_hold_ext_boot.value = 0
        boot = await self._wait_find(
            "boot_rise", _BOOT_RISE_BOUND_CYCLES, write, lambda t, _i: t[_EXT] == 1
        )
        release = await self._wait_find(
            "frst_release", _FRST_RISE_BOUND_CYCLES, boot, lambda t, _i: t[_FRST] == 1
        )
        assert self._all(write - 1, release, _FRST, 0), (
            f"fuse_reset_n rose before the release edge {release}: {rec[write - 1 : release]}"
        )
        count = release - boot
        assert count >= _PIPE_STAGES, (
            f"fuse_reset_n rose {count} edges after ext_boot (edge {boot} to {release}), "
            f"port_table.adoc states {_PIPE_STAGES} pipeline stages (owner value pending)"
        )
        last_edge = min(release + 8, len(rec))
        warm_rise = next((i for i in range(boot, last_edge) if rec[i][_WARM]), None)
        warm_at_boot = rec[boot][_WARM]
        self._done("S3")
        self._chk(
            "CHK-FRST-16-STAGE",
            "ext_boot first read 1 at edge %d, tb_fuse_reset_n 0 on every edge from edge %d to "
            "%d and first read 1 at edge %d: %d edges after ext_boot (adoc minimum %d; exact "
            "count with the input synchroniser is measured, owner value pending); "
            "tb_rst_warm_smc_clk_n was "
            "%d at the ext_boot edge, first high at edge %s (%s edges relative to the release)",
            boot,
            write - 1,
            release - 1,
            release,
            count,
            _PIPE_STAGES,
            warm_at_boot,
            warm_rise,
            "n/a" if warm_rise is None else warm_rise - release,
        )

        # S4
        a_cold2, low2 = await self._cold_reset_low("cold2")
        rel2 = await self._cold_reset_high("cold2", low2)
        sense2 = await self._wait_find(
            "sense_early_boot", _SENSE_BOUND_CYCLES, rel2, lambda t, _i: t[_SENSE] == 1
        )
        early = await self._wait_find(
            "frst_release_early", _FRST_RISE_BOUND_CYCLES, rel2, lambda t, _i: t[_FRST] == 1
        )
        assert early > sense2, (
            f"fuse_reset_n rose at edge {early} before sense done at edge {sense2}"
        )
        assert self._all(rel2, early + 1, _EXT, 1), (
            f"ext_boot dropped between the release (edge {rel2}) and edge {early}"
        )
        assert self._all(rel2, early, _FRST, 0), "fuse_reset_n high before the rise edge"
        count2 = early - sense2
        assert count2 >= _PIPE_STAGES, (
            f"fuse_reset_n rose {count2} edges after sense done (edge {sense2} to {early}), "
            f"port_table.adoc states {_PIPE_STAGES} pipeline stages (owner value pending)"
        )
        self._done("S4")
        self._chk(
            "CHK-FRST-EARLY-BOOT",
            "ext_boot 1 on every edge from the release (edge %d) to the fuse reset rise "
            "(edge %d); tb_fuse_reset_n 0 until sense done at edge %d; the rise came %d edges "
            "after sense done (adoc minimum %d; S3 count after ext_boot was %d, equality is "
            "printed not asserted, owner value pending: %s)",
            rel2,
            early,
            sense2,
            count2,
            _PIPE_STAGES,
            count,
            "equal" if count2 == count else "different",
        )

        # S5
        write = len(rec)
        dut.tb_hold_ext_boot.value = 1
        drop = await self._wait_find(
            "boot_drop", _BOOT_RISE_BOUND_CYCLES, write, lambda t, _i: t[_EXT] == 0
        )
        await self._wait_edges("drop_window", _RESET_BOUND_CYCLES, drop + _WINDOW_EDGES)
        win = rec[drop : drop + _WINDOW_EDGES]
        assert all(t[_EXT] == 0 for t in win), "ext_boot rose inside the drop window"
        levels = sorted({t[_FRST] for t in win})
        changed = next((drop + k for k, t in enumerate(win) if t[_FRST] != win[0][_FRST]), None)
        self._done("S5")
        self._chk(
            "CHK-FRST-BOOT-DROP",
            "ext_boot read 0 at edge %d after tb_hold_ext_boot=1 (it was 1 before); "
            "tb_fuse_reset_n observed levels %s over %d edges from edge %d, first level %d, "
            "change edge %s (the level after a boot-done drop is the owner's open answer, "
            "owner answer pending; nothing else asserted)",
            drop,
            levels,
            _WINDOW_EDGES,
            drop,
            win[0][_FRST],
            changed,
        )

        # S6
        a_cold3, low3 = await self._cold_reset_low("cold3")
        zero = await self._wait_find(
            "frst_rearm", _REARM_BOUND_CYCLES, a_cold3, lambda t, _i: t[_FRST] == 0
        )
        rel3 = await self._cold_reset_high("cold3", low3)
        assert self._all(zero, rel3, _FRST, 0), (
            f"fuse_reset_n rose while the cold reset was held: {rec[zero:rel3]}"
        )
        sense3 = await self._wait_find(
            "sense_rearm", _SENSE_BOUND_CYCLES, rel3, lambda t, _i: t[_SENSE] == 1
        )
        quiet_end = sense3 + _REARM_QUIET_EDGES
        await self._wait_edges("rearm_quiet", _RESET_BOUND_CYCLES, quiet_end + 1)
        assert self._all(rel3, quiet_end + 1, _FRST, 0), (
            f"fuse_reset_n rose with ext_boot low: {rec[rel3 : quiet_end + 1]}"
        )
        assert self._all(rel3, quiet_end + 1, _EXT, 0), "ext_boot rose in the quiet window"
        write = len(rec)
        dut.tb_hold_ext_boot.value = 0
        boot3 = await self._wait_find(
            "boot_rise_second", _BOOT_RISE_BOUND_CYCLES, write, lambda t, _i: t[_EXT] == 1
        )
        rise3 = await self._wait_find(
            "frst_release_second", _FRST_RISE_BOUND_CYCLES, boot3, lambda t, _i: t[_FRST] == 1
        )
        assert rise3 > sense3 and rise3 > boot3, (
            f"fuse_reset_n rose at edge {rise3}, sense done at {sense3}, ext_boot at {boot3}"
        )
        assert self._all(quiet_end + 1, rise3, _FRST, 0), "fuse_reset_n rose before the release"
        self._done("S6")
        self._chk(
            "CHK-FRST-COLD-REARM",
            "tb_fuse_reset_n read 0 %d edges after the cold reset assertion (edge %d) and on "
            "every edge to the release (edge %d); 0 through sense done at edge %d and %d edges "
            "after (edge %d) with ext_boot 0; ext_boot rose at edge %d and fuse_reset_n rose at "
            "edge %d, %d edges later, after sense done and ext_boot",
            zero - a_cold3,
            a_cold3,
            rel3,
            sense3,
            _REARM_QUIET_EDGES,
            quiet_end,
            boot3,
            rise3,
            rise3 - boot3,
        )
        self.access_floor = len(reads)
        self._finish((a_cold, sense, boot, release, early, drop, a_cold3, rise3))
        return stream

    def _finish(self, edges: tuple[int, ...]) -> None:
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert all(b > a for a, b in zip(edges, edges[1:])), f"fence edges not increasing: {edges}"
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(_CHK_STEP), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", _CHK_STEP[ident]) in self._events[:index], (
                    f"{ident} printed before step {_CHK_STEP[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s as measured event edges; checker lines %s; "
            "step stamps %s ps",
            " < ".join(f"{term}@{edge}" for term, edge in zip(_TERMS, edges)),
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
