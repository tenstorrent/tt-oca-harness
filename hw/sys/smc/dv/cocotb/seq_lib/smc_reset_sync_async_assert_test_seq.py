# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset output synchronizers assert asynchronously and release on their own clock edge.

Spec sources: clk_rst.adoc (Reset Synchronization), port_table.adoc.

``powergood_i`` and ``tb_sep_wdt_reset_n`` are driven one third into a clock period. The
reference and periphery outputs fall in the same simulation instant as ``powergood_i``, with no
rising edge of the output's clock at that instant. Every output rises on a rising edge of its
own clock, no earlier than the fourth such edge after its source released, and the measured
edge counts are reported. The warm and watchdog outputs stay low while a re-asserted
``tb_sep_wdt_reset_n`` is low.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, SimTimeoutError, Timer, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_reset_seq_base import SmcResetSeqBase

# 32-stage powergood synchronizer + 32-sample de-glitch + 255-cycle extension.
RELEASE_BOUND_REF_CYCLES = 700
HOLD_POWERGOOD_LOW_REF_CYCLES = 64
WDT_PULSE = 16
WDT_REASSERT_AFTER_EDGES = 2
WDT_POLL_BOUND_SMC_CYCLES = 64
MIN_RELEASE_EDGES = 4
_EDGE_HISTORY = 4096


def _now_ps() -> int:
    return int(round(get_sim_time("ps")))


class _EdgeLog:
    """Rising-edge timestamps (ps) of one clock, kept in a bounded list."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.times: list[int] = []

    async def run(self, clk) -> None:
        while True:
            await RisingEdge(clk)
            self.times.append(_now_ps())
            if len(self.times) > _EDGE_HISTORY:
                del self.times[: len(self.times) - _EDGE_HISTORY]

    def edges_in(self, lo_ps: int, hi_ps: int) -> int:
        """Rising edges with ``lo < t <= hi``."""
        return sum(1 for t in self.times if lo_ps < t <= hi_ps)

    def last(self) -> int | None:
        return self.times[-1] if self.times else None


def _bit(sig) -> int:
    value = sig.value
    assert value.is_resolvable, f"{sig._name} reads {value}: not resolvable"
    return int(value)


class smc_reset_sync_async_assert_test_seq(SmcResetSeqBase):
    """Asynchronous assertion and own-edge release of the synchronized reset outputs."""

    RELEASE_BOUND_REF_CYCLES = RELEASE_BOUND_REF_CYCLES
    STEPS = ("S1", "S2", "S3", "S4", "S5")
    CHECKERS = (
        "CHK-REF-OUTPUTS-ASSERT-ASYNC",
        "CHK-PERIPH-OUTPUT-ASSERTS-ASYNC",
        "CHK-EACH-OUTPUT-RELEASES-ON-OWN-EDGE",
        "CHK-SOURCE-REASSERTS-IN-LATENCY",
    )

    def __init__(self, name: str = "smc_reset_sync_async_assert_test_seq") -> None:
        super().__init__(name)
        self.t_pin_low: int | None = None
        self.t_pg_high: int | None = None
        self.t_wdt_high: int | None = None
        self.t_final_release: int | None = None
        self.release_edges: dict[str, int] = {}
        self.reassert_samples: int | None = None
        self.final_edges: dict[str, int] = {}
        self._step_stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_stamps.append((step_id, _now_ps()))
        cocotb.log.info("STEP %s: %s", step_id, detail)

    def _log_chk(self, chk_id: str, text: str) -> None:
        self._chk_marks.append((chk_id, _now_ps()))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _rise_on_own_edge(self, sig, log: _EdgeLog, t_src_ps: int, bound_ns: float) -> int:
        """Wait for ``sig`` to rise; return the count of own-clock edges in (t_src, t_rise]."""
        label = sig._name
        try:
            await with_timeout(RisingEdge(sig), bound_ns, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{label} did not release within {bound_ns} ns of its source release at "
                f"{t_src_ps} ps (last {log.name} edge {log.last()} ps)"
            ) from exc
        t_rise = _now_ps()
        await ReadOnly()
        assert _bit(sig) == 1, f"{label} rose at {t_rise} ps but reads 0 in the same instant"
        assert t_rise in log.times, (
            f"{label} rose at {t_rise} ps, which is not a {log.name} rising edge "
            f"(last edge {log.last()} ps)"
        )
        count = log.edges_in(t_src_ps, t_rise)
        assert count >= MIN_RELEASE_EDGES, (
            f"{label} rose on {log.name} edge +{count} after the source release at "
            f"{t_src_ps} ps: earlier than the {MIN_RELEASE_EDGES}th edge"
        )
        await RisingEdge(self._clks[log.name])
        return count

    async def body(self) -> None:
        dut = cocotb.top
        periph_n = getattr(dut, "rst_primary_periph_clk_n", None)
        assert periph_n is not None, "rst_primary_periph_clk_n does not resolve on tb_top"
        self._periph_n = periph_n
        self._clks = {
            "clk_ref_i": dut.clk_ref_i,
            "clk_smc_i": dut.clk_smc_i,
            "clk_periph_i": dut.clk_periph_i,
        }
        logs = {name: _EdgeLog(name) for name in self._clks}
        tasks = [cocotb.start_soon(logs[n].run(self._clks[n])) for n in self._clks]
        try:
            await self._scenario(dut, logs)
        finally:
            for task in tasks:
                task.cancel()

    async def _scenario(self, dut, logs: dict[str, _EdgeLog]) -> None:
        ref_log, smc_log, per_log = logs["clk_ref_i"], logs["clk_smc_i"], logs["clk_periph_i"]
        ref_ps = int(round(self.cfg.ref_clk_period_ns * 1000))
        smc_ps = int(round(self.cfg.smc_clk_period_ns * 1000))
        periph_n = self._periph_n
        bound_ns = RELEASE_BOUND_REF_CYCLES * self.cfg.ref_clk_period_ns
        poll_ns = WDT_POLL_BOUND_SMC_CYCLES * self.cfg.smc_clk_period_ns

        # S1 -- fuse sense done, every observable released.
        await self.wait_fuse_sense_done()
        s1 = await self._send(SmcResetOp.SAMPLE)
        assert s1.resolvable, s1
        assert s1.powergood_stable == 1, s1
        assert s1.rst_cold_stable_ref_clk_n == 1, s1
        assert s1.rst_primary_ref_clk_n == 1, s1
        assert s1.rst_primary_smc_clk_n == 1, s1
        assert s1.rst_wdt_smc_clk_n == 1, s1
        assert _bit(periph_n) == 1 and _bit(dut.tb_rst_warm_smc_clk_n) == 1
        self._mark_step("S1", "SETUP fuse sense done, all reset observables released")

        # S2 -- powergood_i falls one third into a clk_ref_i period.
        await RisingEdge(dut.clk_ref_i)
        await Timer(ref_ps // 3, unit="ps")
        self.t_pin_low = _now_ps()
        dut.powergood_i.value = 0
        await ReadOnly()
        cold_v, prim_v = _bit(dut.rst_cold_stable_ref_clk_no), _bit(dut.rst_primary_ref_clk_no)
        periph_v = _bit(periph_n)
        ref_last, per_last = ref_log.last(), per_log.last()
        assert ref_last != self.t_pin_low, "clk_ref_i edge at the powergood_i fall"
        assert cold_v == 0 and prim_v == 0, (
            f"powergood_i fell at {self.t_pin_low} ps; same instant rst_cold_stable_ref_clk_no="
            f"{cold_v} rst_primary_ref_clk_no={prim_v}: assertion is not asynchronous "
            f"(last clk_ref_i edge {ref_last} ps)"
        )
        self._mark_step("S2", "powergood_i low, reference outputs read in the same instant")
        self._log_chk(
            "CHK-REF-OUTPUTS-ASSERT-ASYNC",
            f"powergood_i fell at {self.t_pin_low} ps (no clk_ref_i edge at that instant; last "
            f"edge {ref_last} ps); rst_cold_stable_ref_clk_no=0 and "
            f"rst_primary_ref_clk_no=0 read in the same instant",
        )

        # S3 -- periphery output, same fall.
        assert per_last != self.t_pin_low, "clk_periph_i edge at the powergood_i fall"
        assert periph_v == 0, (
            f"powergood_i fell at {self.t_pin_low} ps; same instant rst_primary_periph_clk_n="
            f"{periph_v}: assertion is not asynchronous (last clk_periph_i edge "
            f"{per_last} ps)"
        )
        await RisingEdge(dut.clk_ref_i)
        self._mark_step("S3", "rst_primary_periph_clk_n low in the same instant as the pin fall")
        self._log_chk(
            "CHK-PERIPH-OUTPUT-ASSERTS-ASYNC",
            f"rst_primary_periph_clk_n=0 at {self.t_pin_low} ps, same instant as the powergood_i "
            f"fall; no clk_periph_i edge at that instant (last edge {per_last} ps)",
        )

        for _ in range(HOLD_POWERGOOD_LOW_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)

        # S4 -- powergood_i release, then a tb_sep_wdt_reset_n pulse.
        await RisingEdge(dut.clk_ref_i)
        await Timer(ref_ps // 3, unit="ps")
        self.t_pg_high = _now_ps()
        outs = (
            ("rst_cold_stable_ref_clk_no", dut.rst_cold_stable_ref_clk_no, ref_log),
            ("rst_primary_ref_clk_no", dut.rst_primary_ref_clk_no, ref_log),
            ("rst_primary_smc_clk_no", dut.rst_primary_smc_clk_no, smc_log),
            ("rst_primary_periph_clk_n", periph_n, per_log),
        )
        for name, sig, _log in outs:
            assert _bit(sig) == 0, f"{name} reads 1 before the powergood_i release"
        dut.powergood_i.value = 1
        waiters = [
            (
                name,
                cocotb.start_soon(self._rise_on_own_edge(sig, log, self.t_pg_high, bound_ns)),
            )
            for name, sig, log in outs
        ]
        for name, waiter in waiters:
            self.release_edges[name] = await waiter
        await self._wait_released("PG_RELEASED")

        dut.tb_sep_wdt_reset_n.value = 0
        wdt_outs = (
            ("rst_wdt_smc_clk_no", dut.rst_wdt_smc_clk_no),
            ("tb_rst_warm_smc_clk_n", dut.tb_rst_warm_smc_clk_n),
        )
        polled = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            polled += 1
            levels = [_bit(sig) for _n, sig in wdt_outs]
            if polled >= WDT_PULSE and levels == [0, 0]:
                break
            assert polled < WDT_POLL_BOUND_SMC_CYCLES, (
                f"after {polled} clk_smc_i edges of tb_sep_wdt_reset_n=0 the outputs read "
                f"{dict(zip([n for n, _s in wdt_outs], levels))}, expected 0"
            )
        await Timer(smc_ps // 3, unit="ps")
        self.t_wdt_high = _now_ps()
        dut.tb_sep_wdt_reset_n.value = 1
        waiters = [
            (
                name,
                cocotb.start_soon(self._rise_on_own_edge(sig, smc_log, self.t_wdt_high, bound_ns)),
            )
            for name, sig in wdt_outs
        ]
        for name, waiter in waiters:
            self.release_edges[name] = await waiter
        e = self.release_edges
        self._mark_step("S4", "powergood_i release and tb_sep_wdt_reset_n pulse, rises timed")
        self._log_chk(
            "CHK-EACH-OUTPUT-RELEASES-ON-OWN-EDGE",
            f"after powergood_i release at {self.t_pg_high} ps: rst_cold_stable_ref_clk_no rose on "
            f"clk_ref_i edge +{e['rst_cold_stable_ref_clk_no']}, rst_primary_ref_clk_no "
            f"+{e['rst_primary_ref_clk_no']} (clk_ref_i), rst_primary_smc_clk_no "
            f"+{e['rst_primary_smc_clk_no']} (clk_smc_i), rst_primary_periph_clk_n "
            f"+{e['rst_primary_periph_clk_n']} (clk_periph_i); after tb_sep_wdt_reset_n release "
            f"at {self.t_wdt_high} ps: rst_wdt_smc_clk_no +{e['rst_wdt_smc_clk_no']} "
            f"(clk_smc_i), tb_rst_warm_smc_clk_n +{e['tb_rst_warm_smc_clk_n']} (clk_smc_i); "
            f"every rise on an own-clock rising edge and no earlier than the "
            f"{MIN_RELEASE_EDGES}th edge",
        )

        # S5 -- release, re-assert after two clk_smc_i edges, release again.
        dut.tb_sep_wdt_reset_n.value = 0
        for _ in range(WDT_PULSE):
            await RisingEdge(dut.clk_smc_i)
        dut.tb_sep_wdt_reset_n.value = 1
        t_first_release = _now_ps()
        early_high = 0
        for _ in range(WDT_REASSERT_AFTER_EDGES):
            await RisingEdge(dut.clk_smc_i)
            early_high += sum(_bit(sig) for _n, sig in wdt_outs)
        dut.tb_sep_wdt_reset_n.value = 0
        samples = 0
        for _ in range(WDT_PULSE):
            await RisingEdge(dut.clk_smc_i)
            for name, sig in wdt_outs:
                assert _bit(sig) == 0, (
                    f"{name} reads 1 at {_now_ps()} ps while the re-asserted "
                    f"tb_sep_wdt_reset_n is low (sample {samples + 1})"
                )
            samples += 1
        self.reassert_samples = samples
        dut.tb_sep_wdt_reset_n.value = 1
        self.t_final_release = _now_ps()
        waiters = [
            (
                name,
                cocotb.start_soon(
                    self._rise_on_own_edge(sig, smc_log, self.t_final_release, poll_ns)
                ),
            )
            for name, sig in wdt_outs
        ]
        for name, waiter in waiters:
            self.final_edges[name] = await waiter
        await self._wait_released("FINAL_RELEASED")
        self._mark_step("S5", "tb_sep_wdt_reset_n re-asserted 2 clk_smc_i after release")
        self._log_chk(
            "CHK-SOURCE-REASSERTS-IN-LATENCY",
            f"tb_sep_wdt_reset_n released at {t_first_release} ps, re-asserted "
            f"{WDT_REASSERT_AFTER_EDGES} clk_smc_i later for {WDT_PULSE} cycles; "
            f"rst_wdt_smc_clk_no and tb_rst_warm_smc_clk_n read 0 at all {samples} clk_smc_i "
            f"samples until the final release and rose {self.final_edges['rst_wdt_smc_clk_no']}/"
            f"{self.final_edges['tb_rst_warm_smc_clk_n']} edges after it (bound "
            f"{WDT_POLL_BOUND_SMC_CYCLES}); output reads 1 in the {WDT_REASSERT_AFTER_EDGES} "
            f"cycles before the re-assertion: {early_high}",
        )
        self._finish_fence()

    def _finish_fence(self) -> None:
        ids = [s for s, _ in self._step_stamps]
        assert ids == list(self.STEPS), f"step order {ids}, expected {list(self.STEPS)}"
        stamps = [t for _, t in self._step_stamps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        chk_ids = [c for c, _ in self._chk_marks]
        assert chk_ids == list(self.CHECKERS), f"checker order {chk_ids}"
        step_time = dict(self._step_stamps)
        for (chk, t_chk), step in zip(self._chk_marks, self.STEPS[1:]):
            assert t_chk >= step_time[step], f"{chk} printed at {t_chk} before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<PASS; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._step_stamps),
        )
