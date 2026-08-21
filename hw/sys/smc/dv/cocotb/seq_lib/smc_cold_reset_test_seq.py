# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_cold_reset_test (DV Skill 1.5 / SMC_001 rev 2).

Exercises SmcResetAgent + SmcClkAgent observations required by the approved
checkbox card: clock edges, bring-up levels, cold assert, powergood gate,
cool primary, and the POR/cool interaction fences. Mid-stimulus snapshots use
RAW_SAMPLE so the scoreboard does not enforce post-release invariants.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_clk_item import SmcClkItem, SmcClkOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from ._one_shot import _OneShot
from .smc_base_test_seq import smc_base_test_seq


class smc_cold_reset_test_seq(smc_base_test_seq):
    """SMC_001 cold-reset / POR / cool path with exact CHK evidence lines."""

    CLK_WINDOW_REF_CYCLES = 64
    BOUND_REF_CYCLES = 200
    RECOVER_REF_CYCLES = 700

    def __init__(self, name: str = "smc_cold_reset_test_seq") -> None:
        super().__init__(name)
        self.sample = None
        self._step_ts: dict[str, float] = {}
        self._timeout_paths: list[str] = []

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _mark_step(self, step_id: str, detail: str) -> None:
        self._step_ts[step_id] = time.monotonic()
        self._log(f"STEP {step_id}: {detail}")

    async def _send(self, op: SmcResetOp) -> SmcResetItem:
        item = SmcResetItem(op.value.lower())
        item.op = op
        await self.start_item(item)
        await self.finish_item(item)
        return item

    async def _wait_raw(
        self,
        predicate,
        *,
        bound: int,
        label: str,
    ) -> SmcResetItem:
        """Poll RAW_SAMPLE until predicate(item) or fail with last state."""
        last = None
        for _ in range(bound):
            await ClockCycles(cocotb.top.clk_ref_i, 1)
            last = await self._send(SmcResetOp.RAW_SAMPLE)
            if not last.resolvable:
                continue
            if predicate(last):
                self._timeout_paths.append(
                    f"{label}: bound={bound} ref_cycles ok last={last}"
                )
                return last
        self._timeout_paths.append(
            f"{label}: bound={bound} ref_cycles EXPIRED last={last}"
        )
        raise AssertionError(
            f"TIMEOUT {label}: bound={bound} ref_cycles last_state={last}"
        )

    async def _recover_sample(self) -> SmcResetItem:
        await ClockCycles(cocotb.top.clk_ref_i, self.RECOVER_REF_CYCLES)
        item = await self._send(SmcResetOp.SAMPLE)
        self.sample = item
        return item

    async def _count_clocks(self) -> SmcClkItem:
        item = SmcClkItem("count_window")
        item.op = SmcClkOp.COUNT_EDGES
        item.window_ref_cycles = self.CLK_WINDOW_REF_CYCLES
        await _OneShot(item, "clk_edges_os").start(self.env.clk_agent.sequencer)
        return item

    async def body(self) -> None:
        # S1 — SETUP (bring-up already done by smc_base_test; restate levels)
        self._mark_step(
            "S1",
            "SETUP clocks running; powergood_i=1 rst_cold_ni=1 rst_cool_ni=1 (post base bring-up)",
        )

        # S2 — clock edges
        self._mark_step("S2", "COUNT_EDGES on clk_smc_i/clk_ref_i/clk_periph_i")
        clk = await self._count_clocks()
        assert clk.smc_rising_edges >= 1, f"clk_smc edges={clk.smc_rising_edges}"
        assert clk.ref_rising_edges >= 1, f"clk_ref edges={clk.ref_rising_edges}"
        assert clk.periph_rising_edges >= 1, f"clk_periph edges={clk.periph_rising_edges}"
        self._log(
            "CHK-CLK-EDGES: in a fixed window "
            f"rising_edges(clk_smc_i)={clk.smc_rising_edges}>=1 AND "
            f"rising_edges(clk_ref_i)={clk.ref_rising_edges}>=1 AND "
            f"rising_edges(clk_periph_i)={clk.periph_rising_edges}>=1"
        )

        # S3 — bring-up SAMPLE
        self._mark_step("S3", "SAMPLE post-bring-up levels")
        s3 = await self._send(SmcResetOp.SAMPLE)
        self.sample = s3
        assert s3.resolvable and s3.powergood_stable == 1
        assert s3.rst_cold_stable_ref_clk_n == 1
        assert s3.rst_primary_ref_clk_n == 1
        assert s3.rst_primary_smc_clk_n == 1
        self._log(
            "CHK-BRINGUP-LEVELS: after bring-up settle SAMPLE: "
            f"powergood_stable_o=={s3.powergood_stable} AND "
            f"rst_cold_stable_ref_clk_no=={s3.rst_cold_stable_ref_clk_n} AND "
            f"rst_primary_ref_clk_no=={s3.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s3.rst_primary_smc_clk_n}"
        )

        # S4 — cold assert (lifecycle: set → observed → cleared → checked_cleared)
        self._mark_step("S4", "COLD_RST_LO then wait primary asserted")
        await self._send(SmcResetOp.COLD_RST_LO)
        self._log("LIFECYCLE CHK-COLD-ASSERT-PRIMARY set: COLD_RST_LO drives rst_cold_ni=0")
        s4 = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 0 and i.rst_primary_smc_clk_n == 0,
            bound=self.BOUND_REF_CYCLES,
            label="COLD_ASSERT_PRIMARY",
        )
        self._log(
            "LIFECYCLE CHK-COLD-ASSERT-PRIMARY observed: "
            f"rst_primary_ref_clk_no=={s4.rst_primary_ref_clk_n}; "
            f"rst_primary_smc_clk_no=={s4.rst_primary_smc_clk_n}"
        )
        self._log(
            "CHK-COLD-ASSERT-PRIMARY: after rst_cold_ni=0, within bound SAMPLE: "
            f"rst_primary_ref_clk_no=={s4.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s4.rst_primary_smc_clk_n}"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        self._log(
            "LIFECYCLE CHK-COLD-ASSERT-PRIMARY cleared: COLD_RST_HI restores rst_cold_ni=1"
        )
        s4c = await self._recover_sample()
        assert s4c.rst_primary_ref_clk_n == 1 and s4c.rst_primary_smc_clk_n == 1, s4c
        self._log(
            "LIFECYCLE CHK-COLD-ASSERT-PRIMARY checked_cleared: SAMPLE "
            f"rst_primary_ref_clk_no=={s4c.rst_primary_ref_clk_n} "
            f"rst_primary_smc_clk_no=={s4c.rst_primary_smc_clk_n}"
        )

        # S5 — powergood gates cold path
        self._mark_step("S5", "POWERGOOD_LO then wait powergood_stable_o==0")
        await self._send(SmcResetOp.POWERGOOD_LO)
        self._log("LIFECYCLE CHK-POWERGOOD-GATES set: POWERGOOD_LO drives powergood_i=0")
        s5 = await self._wait_raw(
            lambda i: i.powergood_stable == 0,
            bound=self.BOUND_REF_CYCLES,
            label="POWERGOOD_GATES",
        )
        self._log(
            f"LIFECYCLE CHK-POWERGOOD-GATES observed: powergood_stable_o=={s5.powergood_stable}"
        )
        self._log(
            "CHK-POWERGOOD-GATES: after powergood_i=0, within bound SAMPLE: "
            f"powergood_stable_o=={s5.powergood_stable}"
        )
        await self._send(SmcResetOp.POWERGOOD_HI)
        self._log(
            "LIFECYCLE CHK-POWERGOOD-GATES cleared: POWERGOOD_HI restores powergood_i=1"
        )
        s5c = await self._recover_sample()
        assert s5c.powergood_stable == 1, s5c
        self._log(
            "LIFECYCLE CHK-POWERGOOD-GATES checked_cleared: SAMPLE "
            f"powergood_stable_o=={s5c.powergood_stable}"
        )

        # S6 — cool assert / release
        self._mark_step("S6", "COOL_RST_LO/HI primary assert/release")
        await self._send(SmcResetOp.COOL_RST_LO)
        self._log("LIFECYCLE CHK-COOL-PRIMARY set: COOL_RST_LO drives rst_cool_ni=0")
        s6a = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 0 and i.rst_primary_smc_clk_n == 0,
            bound=self.BOUND_REF_CYCLES,
            label="COOL_ASSERT_PRIMARY",
        )
        self._log(
            "LIFECYCLE CHK-COOL-PRIMARY observed: "
            f"rst_primary_ref_clk_no=={s6a.rst_primary_ref_clk_n}; "
            f"rst_primary_smc_clk_no=={s6a.rst_primary_smc_clk_n}"
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        self._log("LIFECYCLE CHK-COOL-PRIMARY cleared: COOL_RST_HI drives rst_cool_ni=1")
        s6b = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 1 and i.rst_primary_smc_clk_n == 1,
            bound=self.RECOVER_REF_CYCLES,
            label="COOL_RELEASE_PRIMARY",
        )
        self._log(
            "LIFECYCLE CHK-COOL-PRIMARY checked_cleared: SAMPLE "
            f"rst_primary_ref_clk_no=={s6b.rst_primary_ref_clk_n} "
            f"rst_primary_smc_clk_no=={s6b.rst_primary_smc_clk_n}"
        )
        self._log(
            "CHK-COOL-PRIMARY: after rst_cool_ni=0, within bound SAMPLE "
            f"rst_primary_ref_clk_no=={s6a.rst_primary_ref_clk_n} AND "
            f"rst_primary_smc_clk_no=={s6a.rst_primary_smc_clk_n}; "
            f"after rst_cool_ni=1, within bound SAMPLE both "
            f"==({s6b.rst_primary_ref_clk_n},{s6b.rst_primary_smc_clk_n})"
        )
        await self._recover_sample()

        # S7 — INT-POR-QUALIFIES-COLD-RESET
        self._mark_step("S7", "POR qualifies cold reset joint observation")
        await self._send(SmcResetOp.POWERGOOD_LO)
        pg0 = await self._wait_raw(
            lambda i: i.powergood_stable == 0,
            bound=self.BOUND_REF_CYCLES,
            label="INT_POR_PG0",
        )
        gated_ref = pg0.rst_primary_ref_clk_n
        gated_smc = pg0.rst_primary_smc_clk_n
        await self._send(SmcResetOp.COLD_RST_LO)
        # Bounded poll: cold while PG gated must keep primary at pre-qualify levels
        # (fail_on: cold moves primary to released while powergood_stable_o==0).
        cold_while_pg0 = await self._wait_raw(
            lambda i: (
                i.powergood_stable == 0
                and i.rst_primary_ref_clk_n == gated_ref
                and i.rst_primary_smc_clk_n == gated_smc
            ),
            bound=self.BOUND_REF_CYCLES,
            label="INT_POR_COLD_WHILE_PG0",
        )
        assert not (
            cold_while_pg0.rst_primary_ref_clk_n == 1
            and cold_while_pg0.rst_primary_smc_clk_n == 1
        ), f"primary released while powergood_stable==0: {cold_while_pg0}"
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._send(SmcResetOp.POWERGOOD_HI)
        await self._recover_sample()
        await self._send(SmcResetOp.COLD_RST_LO)
        cold_while_pg1 = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 0 and i.rst_primary_smc_clk_n == 0,
            bound=self.BOUND_REF_CYCLES,
            label="INT_POR_COLD_WHILE_PG1",
        )
        self._log(
            "CHK-INT-POR-COLD: ordered joint: (1) with powergood_stable_o==0, "
            f"COLD_RST_LO leaves rst_primary_ref_clk_no=={cold_while_pg0.rst_primary_ref_clk_n} "
            f"and rst_primary_smc_clk_no=={cold_while_pg0.rst_primary_smc_clk_n} "
            f"(pre-qualify gated levels ref={gated_ref} smc={gated_smc}); "
            f"(2) after powergood_stable_o==1 settle and COLD_RST_LO, both primary samples "
            f"==({cold_while_pg1.rst_primary_ref_clk_n},{cold_while_pg1.rst_primary_smc_clk_n})"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._recover_sample()

        # S8 — INT-COOL-PIN-TO-RESET-SEQUENCE
        self._mark_step("S8", "cool pin reset sequence joint observation")
        await self._send(SmcResetOp.COOL_RST_LO)
        cool_lo = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 0 and i.rst_primary_smc_clk_n == 0,
            bound=self.BOUND_REF_CYCLES,
            label="INT_COOL_LO",
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        cool_hi = await self._wait_raw(
            lambda i: i.rst_primary_ref_clk_n == 1 and i.rst_primary_smc_clk_n == 1,
            bound=self.RECOVER_REF_CYCLES,
            label="INT_COOL_HI",
        )
        self._log(
            "CHK-INT-COOL-SEQ: ordered joint: COOL_RST_LO then SAMPLE "
            f"rst_primary_ref_clk_no=={cool_lo.rst_primary_ref_clk_n} and "
            f"rst_primary_smc_clk_no=={cool_lo.rst_primary_smc_clk_n} within bound; "
            f"COOL_RST_HI then SAMPLE both "
            f"==({cool_hi.rst_primary_ref_clk_n},{cool_hi.rst_primary_smc_clk_n}) within bound"
        )
        await self._recover_sample()

        # S9 TIMEOUT bookkeeping + NONVAC fence
        self._mark_step("S9", "TIMEOUT path bookkeeping")
        order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
        for a, b in zip(order, order[1:]):
            assert self._step_ts[a] <= self._step_ts[b], f"order {a} !< {b}"
        self._log(
            "CHK-NONVAC: SETUP < S2 < S3 < S4 < S5 < S6 < S7 < S8 < PASS"
        )
        for line in self._timeout_paths:
            self._log(f"CHK-TIMEOUT-PATHS: {line}")
        self._log(
            "CHK-TIMEOUT-PATHS: each bounded wait logs a finite bound, "
            "fail-on-expiry path, and last state"
        )
        self._log("SMC_001 scenario PASS")
