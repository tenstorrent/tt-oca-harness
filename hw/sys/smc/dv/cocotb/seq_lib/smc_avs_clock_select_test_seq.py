# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CLOCK_SELECT table, ordered transitions and ungated-change recovery.

Contract SMC_CLOCK_SRC_008, anchor smc_avs_clock_select_test.
Scenarios CSRC-AVS-SELECT.S1 to CSRC-AVS-SELECT.S6.
Sources: avsbus_controller.rdl AVS_CLOCK_SELECT, hw/ip/avsbus_controller/doc/interface.adoc.

The select encoding is 00 periph clock direct, 01 periph clock divided, 10 ref clock direct,
11 ref clock divided; the divider holds its reset value of 4. Each programmed value goes
through the gated sequence: set TURN_OFF_ALL_PREMUX_CLOCKS, write the select, clear it.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import Edge, First, Timer
from cocotb.utils import get_sim_time

from .smc_avsbus_protocol_utils import AVS_CFG_1, avs_field
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_SELECT_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__AVS_CLOCK_SELECT_bm")
CLOCK_SELECT_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__AVS_CLOCK_SELECT_bp")
PREMUX_OFF_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__TURN_OFF_ALL_PREMUX_CLOCKS_bm")
STOP_ON_IDLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__STOP_AVS_CLOCK_ON_IDLE_bm")

PERIPH_PERIOD_PS = 5_000
REF_PERIOD_PS = 10_000
DIVISOR = 4
#: Select encoding to expected period in ps at the default 10 / 5 ns triple.
TABLE_PS = {
    0: PERIPH_PERIOD_PS,
    1: DIVISOR * PERIPH_PERIOD_PS,
    2: REF_PERIOD_PS,
    3: DIVISOR * REF_PERIOD_PS,
}
MEASURE_PERIODS = 8
EDGE_TIMEOUT_NS = 100_000
FENCE = (
    "SELECT_TABLE_MEASURED",
    "TRANSITIONS_12_DONE",
    "UNGATED_WRITE",
    "GATED_RECOVERY_MEASURED",
)
CHK_ORDER = (
    "CHK-AVS-SELECT-TABLE",
    "CHK-AVS-SELECT-TRANSITIONS",
    "CHK-AVS-SELECT-UNGATED-RECOVERY",
)


class NoPadEdge(AssertionError):
    """No AVS clock edge reached the pad inside the bounded wait."""


class smc_avs_clock_select_test_seq(SmcCsrSeq):
    """Every AVS_CLOCK_SELECT value and change must show its table period at the pad."""

    def __init__(self, name: str = "smc_avs_clock_select_test_seq") -> None:
        super().__init__(name)
        self._waits: dict[str, list] = {}
        self._steps: list[tuple[str, int]] = []
        self._chk_after: list[tuple[str, str]] = []
        self._cfg = 0

    @staticmethod
    def _clk() -> int:
        raw = cocotb.top.tb_avs_clk_from_dut.value
        assert raw.is_resolvable, f"the AVS clock at the pad is not resolvable: {raw}"
        return int(raw)

    def _note_wait(self, name: str, state: str) -> None:
        self._waits.setdefault(name, [EDGE_TIMEOUT_NS, state])[1] = state

    async def _next_edge(self, label: str) -> None:
        result = await First(
            Edge(cocotb.top.tb_avs_clk_from_dut), Timer(EDGE_TIMEOUT_NS, unit="ns")
        )
        if not isinstance(result, Edge):
            raise NoPadEdge(
                f"{label}: no AVS clock edge at the pad in {EDGE_TIMEOUT_NS} ns; "
                f"last pad level {self._clk()}"
            )
        self._note_wait("avs_edge", f"level{self._clk()}")

    async def _measure(self, label: str) -> tuple[int, float, list[int]]:
        """Mean period in ps over 8 rising-edge periods, the high fraction, the rise times."""
        while self._clk() != 0:
            await self._next_edge(f"{label} align low")
        await self._next_edge(f"{label} first rise")
        start = int(get_sim_time("ps"))
        high_ps = 0
        rose = start
        rises = [start]
        for n in range(MEASURE_PERIODS):
            await self._next_edge(f"{label} fall {n}")
            high_ps += int(get_sim_time("ps")) - rose
            await self._next_edge(f"{label} rise {n}")
            rose = int(get_sim_time("ps"))
            rises.append(rose)
        span = rose - start
        assert span > 0, f"{label}: {MEASURE_PERIODS} AVS clock periods spanned 0 ps"
        return round(span / MEASURE_PERIODS), high_ps / span, rises

    async def _measure_settled(self, label: str, want_ps: int) -> tuple[int, float, int]:
        """Measure windows until one has every rise-to-rise period at the table value.

        The select change reaches the pad some time after the gate is released, so a window
        may straddle the old and new clock. Windows are repeated inside the edge-wait bound
        and expiry reports the last window measured.
        """
        deadline = get_sim_time("ns") + EDGE_TIMEOUT_NS
        discarded = 0
        while True:
            period, high, rises = await self._measure(label)
            gaps = {b - a for a, b in zip(rises, rises[1:])}
            if gaps == {want_ps}:
                self._note_wait("settle_windows", f"discarded{discarded}")
                return period, high, discarded
            discarded += 1
            if get_sim_time("ns") > deadline:
                raise AssertionError(
                    f"{label}: no window at {want_ps} ps in {EDGE_TIMEOUT_NS} ns; "
                    f"last window mean {period} ps, rise gaps {sorted(gaps)} ps, "
                    f"last pad level {self._clk()}"
                )

    async def _gated_select(self, label: str, select: int) -> None:
        """Gate set keeps the live select, the new select is written inside the gate."""
        prev = self._cfg
        want = (prev & ~(CLOCK_SELECT_BM | PREMUX_OFF_BM)) | (
            (select << CLOCK_SELECT_BP) & CLOCK_SELECT_BM
        )
        await self.csr_write(f"AVS_CFG_1_PREMUX_OFF_{label}", AVS_CFG_1, prev | PREMUX_OFF_BM)
        await self.csr_write(f"AVS_CFG_1_SEL_{label}", AVS_CFG_1, want | PREMUX_OFF_BM)
        await self.csr_write(f"AVS_CFG_1_PREMUX_ON_{label}", AVS_CFG_1, want)
        await self.csr_read(f"AVS_CFG_1_RB_{label}", AVS_CFG_1, expected=want)
        self._cfg = want

    async def _program_measure(self, label: str, select: int) -> tuple[int, float, int]:
        await self._gated_select(label, select)
        period, high, discarded = await self._measure_settled(label, TABLE_PS[select])
        cocotb.log.info("%s: select %d after %d discarded windows", label, select, discarded)
        return period, high, discarded

    def _stamp(self, step: str) -> None:
        self._steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, line: str) -> None:
        cocotb.log.info("%s", line)
        self._chk_after.append((cid, self._steps[-1][0]))

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_avs_clk_from_dut"), "tb_avs_clk_from_dut is not exported"
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        cfg1 = await self.csr_read("AVS_CFG_1_SAVE", AVS_CFG_1)
        self._cfg = cfg1 & ~PREMUX_OFF_BM
        assert (cfg1 & STOP_ON_IDLE_BM) == 0, (
            f"STOP_AVS_CLOCK_ON_IDLE is set (AVS_CFG_1=0x{cfg1:08x}); the pad clock may stop"
        )
        cocotb.log.info("STEP S1: AVS_CFG_1=0x%08x, STOP_AVS_CLOCK_ON_IDLE clear", cfg1)
        self._stamp("S1")

        # S2: the select table.
        rows = []
        for select in (0, 1, 2, 3):
            period, high, _ = await self._program_measure(f"TAB{select}", select)
            want = TABLE_PS[select]
            assert period == want, (
                f"select {select}: AVS clock period {period} ps, table says {want} ps"
            )
            rows.append(f"sel{select}={period}ps(high {100 * high:.1f}%)")
            cocotb.log.info(
                "STEP S2: select %d period %d ps high %.1f%%", select, period, high * 100
            )
        self._stamp("SELECT_TABLE_MEASURED")
        self._chk(
            "CHK-AVS-SELECT-TABLE",
            "CHK-AVS-SELECT-TABLE: gated select table at ref 10 ns / periph 5 ns, divider "
            f"{DIVISOR}, 8 periods each: " + " ".join(rows) + "; read-back equal to written",
        )

        # S3: all 12 ordered pairs.
        pairs = [(a, b) for a in range(4) for b in range(4) if a != b]
        random.Random(seed).shuffle(pairs)
        assert len(set(pairs)) == 12, f"expected 12 distinct pairs, drew {len(set(pairs))}"
        done = []
        for a, b in pairs:
            pre, _, pre_disc = await self._program_measure(f"T{a}to{b}_FROM", a)
            assert pre == TABLE_PS[a], f"before {a}->{b}: period {pre} ps, table {TABLE_PS[a]} ps"
            period, high, disc = await self._program_measure(f"T{a}to{b}", b)
            want = TABLE_PS[b]
            assert period == want, (
                f"transition {a}->{b}: period {period} ps, table for select {b} is {want} ps"
            )
            done.append(f"{a}->{b}=pre{pre}ps/new{period}ps/discarded{disc}(pre{pre_disc})")
            cocotb.log.info("STEP S3: %d->%d period %d ps high %.1f%%", a, b, period, high * 100)
        self._stamp("TRANSITIONS_12_DONE")
        self._chk(
            "CHK-AVS-SELECT-TRANSITIONS",
            f"CHK-AVS-SELECT-TRANSITIONS: {len(done)} distinct ordered pairs in seed {seed} "
            "order, each at the new table period: " + " ".join(done),
        )
        last = pairs[-1][1]

        # S4: ungated change, then gated reprogram of the same value.
        target = (last + 1) % 4
        want_reg = (self._cfg & ~CLOCK_SELECT_BM) | (target << CLOCK_SELECT_BP)
        await self.csr_write("AVS_CFG_1_UNGATED", AVS_CFG_1, want_reg)
        await self.csr_read("AVS_CFG_1_UNGATED_RB", AVS_CFG_1, expected=want_reg)
        self._cfg = want_reg
        self._stamp("UNGATED_WRITE")
        ungated = "stopped"
        try:
            up, uhigh, _ = await self._measure("UNGATED")
            ungated = f"period {up} ps high {100 * uhigh:.1f}% (table {TABLE_PS[target]} ps)"
        except NoPadEdge as exc:
            ungated = f"no edge within bound ({exc})"
        cocotb.log.info(
            "STEP S4: ungated select %d -> %d, unguarded-interval clock: %s", last, target, ungated
        )
        period, high, _ = await self._program_measure("RECOVER", target)
        want = TABLE_PS[target]
        assert period == want, (
            f"gated reprogram of select {target}: period {period} ps, table says {want} ps"
        )
        self._stamp("GATED_RECOVERY_MEASURED")
        self._chk(
            "CHK-AVS-SELECT-UNGATED-RECOVERY",
            f"CHK-AVS-SELECT-UNGATED-RECOVERY: ungated select {last}->{target} behaviour: "
            f"{ungated}; owner answers SF-019; gated reprogram period {period} ps equals table "
            f"{want} ps, high {100 * high:.1f}%",
        )

        # S5 and the fence.
        axi_bound = self.cfg.axi_timeout_ns
        names = ", ".join(f"{n}={b}ns last={s}" for n, (b, s) in self._waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s, sep_in_access=%dns last=ok; "
            "expiry raises AssertionError with the last pad level",
            len(self._waits) + 1,
            names,
            axi_bound,
        )
        stamps = [t for _, t in self._steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        order = [s for s, _ in self._steps if s in FENCE]
        assert order == list(FENCE), f"fence order {order}"
        assert [c for c, _ in self._chk_after] == list(CHK_ORDER), self._chk_after
        fence_t = dict(self._steps)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE),
            ",".join(CHK_ORDER),
            ",".join(f"{s}={fence_t[s]}" for s, _ in self._steps),
        )
