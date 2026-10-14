# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold-boot release of the CPU resets and the boundary self-isolation.

Sources: cpu.adoc (Reset and Boot, Memory Repair, CPU AXI Isolation), clk_rst.adoc.

A sampler records the probes of this test on every clk_smc_i rising edge; every check is
made over that record, and every wait is a bounded count of edges. Requires +smc_hold_ext_boot.
The checker lines print in step order after the last step, each after its own compare.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
_CHK_ORDER = (
    "CHK-FUSE-CORES-HELD-UNTIL-SENSE",
    "CHK-FUSE-HELD-WITHOUT-EXT-BOOT",
    "CHK-FUSE-RELEASE-BOTH-TERMS",
    "CHK-INIT-MEM-DONE-BYPASS",
    "CHK-COLD-SELF-ISOLATE-HELD",
    "CHK-COLD-SELF-ISOLATE-RELEASE",
    "CHK-FUSE-EXT-BOOT-MID-SENSE",
)
_CHK_STEP = {
    "CHK-FUSE-CORES-HELD-UNTIL-SENSE": "S2",
    "CHK-FUSE-HELD-WITHOUT-EXT-BOOT": "S3",
    "CHK-FUSE-RELEASE-BOTH-TERMS": "S4",
    "CHK-FUSE-EXT-BOOT-MID-SENSE": "S7",
    "CHK-INIT-MEM-DONE-BYPASS": "S5",
    "CHK-COLD-SELF-ISOLATE-HELD": "S6",
    "CHK-COLD-SELF-ISOLATE-RELEASE": "S6",
}
_WINDOW_EDGES = 64
_SENSE_BOUND_CYCLES = 200_000
_RESET_BOUND_CYCLES = 2_000
_RELEASE_BOUND_CYCLES = 20_000
_BOOT_RISE_BOUND_CYCLES = 16
_CPU_RELEASE_BOUND_CYCLES = 20_000
_INIT_BOUND_CYCLES = 20_000
_ISOLATE_BOUND_CYCLES = 2_000
(_RST, _SENSE, _FRST, _WARM, _EXT, _CORES, _UNC, _INIT, _ISO, _REQ) = range(10)
_PROBES = (
    "rst_primary_smc_clk_no",
    "tb_fuse_sense_done",
    "tb_fuse_reset_n",
    "tb_rst_warm_smc_clk_n",
    "tb_hold_ext_boot",
    "tb_cpu_core_resets_n",
    "tb_cpu_uncore_reset_n",
    "smc_init_mem_done_o",
    "tb_cpu_cluster_isolate",
    "tb_cpu_isolate_req",
)


class smc_cpu_boot_release_sequence_test_seq(SmcResetSeqBase):
    """CPU reset release against fuse sense, ext boot, init-done and the isolate window."""

    def __init__(self, name: str = "smc_cpu_boot_release_sequence_test_seq") -> None:
        super().__init__(name)
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []
        self._rec: list[tuple[int, ...]] = []
        self._lines: dict[str, tuple[str, tuple]] = {}
        self._core_full = 0
        self._unc_full = 0

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _stash(self, chk_id: str, fmt: str, *args) -> None:
        self._lines[chk_id] = (fmt, args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _ext_boot(self) -> int:
        return 1 - self._sig("tb_hold_ext_boot")

    def _sample(self) -> tuple[int, ...]:
        s = [self._sig(p) for p in _PROBES]
        s[_EXT] = self._ext_boot()
        return tuple(s)

    def _last(self) -> str:
        if not self._rec:
            return "no sample"
        return f"(edge={len(self._rec) - 1},{dict(zip(_PROBES, self._rec[-1]))})"

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self._rec.append(self._sample())

    # --- waits ----------------------------------------------------------
    async def _wait_find(self, name: str, bound: int, start: int, test) -> int:
        """First recorded edge at or after `start` where test(sample) holds."""
        index = start
        waited = 0
        while True:
            while index < len(self._rec):
                if test(self._rec[index]):
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
        await self._wait_find(name, bound, count - 1, lambda _t: True)

    def _cpu_up(self, t: tuple[int, ...]) -> bool:
        return t[_CORES] != 0 or t[_UNC] != 0

    def _released(self, t: tuple[int, ...]) -> bool:
        return t[_CORES] == self._core_full and t[_UNC] == self._unc_full

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
            f"{tag}_reset_asserted", _RESET_BOUND_CYCLES, assert_edge, lambda t: t[_RST] == 0
        )
        return assert_edge, low

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        for name in (*_PROBES, "clk_smc_i"):
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        assert self._sig("tb_hold_ext_boot") == 1, (
            "+smc_hold_ext_boot required so ext_boot_seq_done stays 0 from t=0"
        )
        self._core_full = (1 << len(dut.tb_cpu_core_resets_n)) - 1
        self._unc_full = (1 << len(dut.tb_cpu_uncore_reset_n)) - 1
        for waited in range(_SENSE_BOUND_CYCLES + 1):
            if self._sig("tb_fuse_sense_done"):
                break
            if waited == _SENSE_BOUND_CYCLES:
                raise AssertionError(
                    f"bringup_sense: tb_fuse_sense_done not 1 within {_SENSE_BOUND_CYCLES} smc "
                    f"clocks"
                )
            await RisingEdge(dut.clk_smc_i)
        self._waits.append(
            ("bringup_sense", _SENSE_BOUND_CYCLES, "tb_fuse_sense_done=1 before the record")
        )
        sampler = cocotb.start_soon(self._sampler())
        try:
            await self._scenario()
        finally:
            sampler.cancel()

    async def _scenario(self) -> None:
        dut = cocotb.top
        rec = self._rec
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        await NextTimeStep()

        # S1
        a_cold, low = await self._cold_reset_low("cold1")
        await self._send(SmcResetOp.COLD_RST_HI)
        rel = await self._wait_find("cold1_release", _RELEASE_BOUND_CYCLES, low, lambda t: t[_RST])
        self._done("S1")

        # S2
        assert rec[rel][_SENSE] == 0, (
            f"tb_fuse_sense_done already 1 at the cold reset release edge {rel}: empty S2 slice"
        )
        sense = await self._wait_find(
            "sense_done", _SENSE_BOUND_CYCLES, rel, lambda t: t[_SENSE] == 1
        )
        assert all(not self._cpu_up(t) for t in rec[rel:sense]), (
            f"a CPU reset output read 1 before the sense-done edge {sense}: {rec[rel:sense]}"
        )
        sense_low = next((i for i in range(a_cold, sense) if rec[i][_SENSE] == 0), None)
        self._done("S2")
        self._stash(
            "CHK-FUSE-CORES-HELD-UNTIL-SENSE",
            "tb_cpu_core_resets_n and tb_cpu_uncore_reset_n 0 on all %d recorded edges from the "
            "cold reset release (edge %d) to the first edge with tb_fuse_sense_done=1 (edge %d, "
            "cold reset asserted at edge %d, sense first read 0 at edge %s)",
            sense - rel,
            rel,
            sense,
            a_cold,
            sense_low,
        )

        # S3
        window_end = sense + _WINDOW_EDGES
        await self._wait_edges("held_window", _RESET_BOUND_CYCLES, window_end)
        win = rec[sense:window_end]
        assert len(win) == _WINDOW_EDGES and all(t[_SENSE] == 1 for t in win), (
            f"sense done not 1 across the window: {win}"
        )
        assert all(t[_EXT] == 0 for t in win), f"ext_boot_seq_done not 0 in the window: {win}"
        assert all(not self._cpu_up(t) for t in win), f"a CPU reset output read 1: {win}"
        self._done("S3")
        self._stash(
            "CHK-FUSE-HELD-WITHOUT-EXT-BOOT",
            "tb_fuse_sense_done 1 and ext_boot_seq_done 0, every core reset output and the uncore "
            "reset output 0 on %d of %d consecutive edges %d..%d; tb_fuse_reset_n levels %s, "
            "tb_rst_warm_smc_clk_n levels %s",
            len(win),
            _WINDOW_EDGES,
            sense,
            window_end - 1,
            sorted({t[_FRST] for t in win}),
            sorted({t[_WARM] for t in win}),
        )

        # S4
        write = len(rec)
        dut.tb_hold_ext_boot.value = 0
        boot = await self._wait_find(
            "boot_rise", _BOOT_RISE_BOUND_CYCLES, write, lambda t: t[_EXT] == 1
        )
        release = await self._wait_find(
            "cpu_release", _CPU_RELEASE_BOUND_CYCLES, write, self._released
        )
        assert release > sense and release > boot, (
            f"CPU resets released at edge {release}, sense done at {sense}, ext_boot at {boot}"
        )
        assert all(not self._released(t) for t in rec[sense:release]), "release before the edge"
        self._done("S4")
        self._stash(
            "CHK-FUSE-RELEASE-BOTH-TERMS",
            "all core reset outputs and the uncore reset output first read 1 at edge %d, %d edges "
            "after the ext_boot rise (edge %d) and %d edges after the sense-done rise (edge %d); "
            "latency is not specified, measured, not compared",
            release,
            release - boot,
            boot,
            release - sense,
            sense,
        )

        # S5
        await self._wait_edges("post_release", _RESET_BOUND_CYCLES, release + 2)
        init_first = await self._wait_find(
            "init_mem_done", _INIT_BOUND_CYCLES, a_cold, lambda t: t[_INIT] == 1
        )
        up = [i for i, t in enumerate(rec) if self._cpu_up(t)]
        assert up, "no CPU reset output read 1 in the record"
        bad = [i for i in up if rec[i][_INIT] != 1]
        assert not bad, f"smc_init_mem_done_o read 0 while a CPU reset output read 1: edges {bad}"
        core_rel = next(i for i in range(a_cold, len(rec)) if rec[i][_CORES] == self._core_full)
        unc_rel = next(i for i in range(a_cold, len(rec)) if rec[i][_UNC] == self._unc_full)
        self._done("S5")
        self._stash(
            "CHK-INIT-MEM-DONE-BYPASS",
            "smc_init_mem_done_o read 1 on all %d recorded edges with a CPU reset output at 1 "
            "(first %d, last %d); first read 1 at edge %d (cold reset asserted at edge %d, "
            "smc_disable_sram_auto_init_i held 1 by the bench, strap mapping not specified, "
            "measured)",
            len(up),
            up[0],
            up[-1],
            init_first,
            a_cold,
        )

        # S6
        latest = max(init_first, core_rel, unc_rel)
        fall = await self._wait_find(
            "isolate_fall", _ISOLATE_BOUND_CYCLES, rel, lambda t: t[_ISO] == 0
        )
        await self._wait_edges("isolate_after", _RESET_BOUND_CYCLES, fall + 2)
        assert fall > rel and rec[rel][_ISO] == 1, (
            f"tb_cpu_cluster_isolate read 0 at the first edge {rel} after rst_primary released"
        )
        assert all(t[_ISO] == 1 for t in rec[rel:fall]), (
            f"tb_cpu_cluster_isolate read 0 inside the window: {rec[rel:fall]}"
        )
        assert fall > latest, (
            f"tb_cpu_cluster_isolate fell at edge {fall}, latest of init-done {init_first}, "
            f"core release {core_rel}, uncore release {unc_rel} is edge {latest}"
        )
        self._done("S6")
        self._stash(
            "CHK-COLD-SELF-ISOLATE-HELD",
            "tb_cpu_cluster_isolate 1 on all %d recorded edges from the first edge after "
            "rst_primary released (edge %d) to its release edge %d; tb_cpu_isolate_req %d at "
            "the edge before the release and %d at it",
            fall - rel,
            rel,
            fall,
            rec[fall - 1][_REQ],
            rec[fall][_REQ],
        )
        self._stash(
            "CHK-COLD-SELF-ISOLATE-RELEASE",
            "tb_cpu_cluster_isolate fell at edge %d, %d clk_smc_i rises after the latest of "
            "init-done (edge %d), core release (edge %d) and uncore release (edge %d); the spec "
            "gives four cycles, clock and counting rule not specified (measured, "
            "not compared)",
            fall,
            fall - latest,
            init_first,
            core_rel,
            unc_rel,
        )

        # S7
        dut.tb_hold_ext_boot.value = 1
        a_cold2, low2 = await self._cold_reset_low("cold2")
        await self._send(SmcResetOp.COLD_RST_HI)
        rel2 = await self._wait_find(
            "cold2_release", _RELEASE_BOUND_CYCLES, low2, lambda t: t[_RST] == 1
        )
        assert rec[rel2][_SENSE] == 0 and rec[-1][_SENSE] == 0, (
            f"tb_fuse_sense_done already 1 at the ext_boot drive (release edge {rel2}, "
            f"{self._last()}): no mid-sensing window"
        )
        drive = len(rec)
        dut.tb_hold_ext_boot.value = 0
        sense2 = await self._wait_find(
            "sense_done_second", _SENSE_BOUND_CYCLES, drive, lambda t: t[_SENSE] == 1
        )
        release2 = await self._wait_find(
            "cpu_release_second", _CPU_RELEASE_BOUND_CYCLES, drive, self._released
        )
        assert all(not self._cpu_up(t) for t in rec[rel2:sense2]), (
            f"a CPU reset output read 1 before the sense-done edge {sense2}: {rec[rel2:sense2]}"
        )
        assert release2 > sense2, (
            f"CPU resets released at edge {release2}, sense done at edge {sense2}"
        )
        await self._wait_released("cold2 settle")
        self._done("S7")
        self._stash(
            "CHK-FUSE-EXT-BOOT-MID-SENSE",
            "tb_hold_ext_boot driven 0 at edge %d with tb_fuse_sense_done 0 (cold reset release "
            "edge %d); no CPU reset output 1 before sense done at edge %d; all CPU resets "
            "released at edge %d, %d edges after sense done (latency not specified, "
            "measured, not compared)",
            drive,
            rel2,
            sense2,
            release2,
            release2 - sense2,
        )
        self._finish((a_cold, rel, sense, release, init_first, fall, rel2, release2, a_cold2))

    def _finish(self, edges: tuple[int, ...]) -> None:
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        assert set(self._lines) == set(_CHK_ORDER), f"checker lines {sorted(self._lines)}"
        for ident in _CHK_ORDER:
            assert ("step", _CHK_STEP[ident]) in self._events, f"{ident} step not completed"
            fmt, args = self._lines[ident]
            self._events.append(("chk", ident))
            cocotb.log.info("%s: " + fmt, ident, *args)
        printed = [i for k, i in self._events if k == "chk"]
        assert printed == list(_CHK_ORDER), f"checker lines printed {printed}"
        order = [_STEPS.index(_CHK_STEP[i]) for i in printed]
        assert order == sorted(order), f"checker lines not in step order: {printed}"
        (a_cold, rel, sense, release, init_first, fall, rel2, release2, a_cold2) = edges
        chain = (a_cold, rel, sense, release, fall, a_cold2, rel2, release2)
        assert all(b > a for a, b in zip(chain, chain[1:])), f"fence edges not increasing: {edges}"
        assert a_cold <= init_first <= release, f"init-done edge {init_first} outside the record"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence COLD_ASSERT@%d < COLD_RELEASE@%d < SENSE_DONE@%d < "
            "CPU_RELEASE@%d < ISOLATE_FALL@%d < SECOND_COLD_ASSERT@%d < SECOND_RELEASE@%d < "
            "SECOND_CPU_RELEASE@%d, with COLD_ASSERT@%d <= INIT_DONE@%d <= CPU_RELEASE@%d; "
            "checker lines %s; step stamps %s ps"
            % (
                a_cold,
                rel,
                sense,
                release,
                fall,
                a_cold2,
                rel2,
                release2,
                a_cold,
                init_first,
                release,
                ", ".join(printed),
                ", ".join(f"{s}={t}" for s, t in self._stamps),
            )
        )
