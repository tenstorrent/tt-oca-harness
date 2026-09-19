# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_sanity_test.

Implements the DTP VPLAN sanity scenario: exercise the IEEE 1149.1 TAP finite
state machine by visiting and checking all primary TAP controller states,
scan patterns through BYPASS, and force Test-Logic-Reset with five TMS-high
cycles. Every comparison lands as named ``CHK-*`` evidence through the family
checker, finalized once per pass. The SV-UVM twin is
``uvm/seq_lib/dtp_sanity_test_seq.svh``.
"""

from __future__ import annotations

import random

from env.dtp_types import DtpJtagInstr, DtpTapState
from ocah_jtag_vip import TLR_TMS_ONES, OcahJtagChecker

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

VISIT_ALL_CHECK_ID = "CHK-TAP-VISIT-ALL"
GOTO_CHECK_ID = "CHK-TAP-GOTO"
# CHK-TAP-RESET-TLR and CHK-TAP-STATE come from the attached checker on every
# TAP reset and raw TMS step; the others are this sequence's own records.
REQUIRED_CHECK_IDS: frozenset[str] = frozenset(
    {
        "CHK-TAP-RESET-TLR",
        "CHK-TAP-STATE",
        GOTO_CHECK_ID,
        "CHK-TAP-TLR-TMS5",
        VISIT_ALL_CHECK_ID,
        "CHK-IR-DECODE",
        "CHK-BYPASS-DELAY",
        "CHK-NONVAC",
    }
)
BYPASS_WIDTH = 64
# Directed pattern whose one-TCK-delayed image differs from a pass-through.
BYPASS_DIRECTED_PATTERN = 0xA5A5_5A5A_C3C3_3C3C
BYPASS_RANDOM_PATTERNS = 2


class dtp_sanity_test_seq(dtp_jtag_base_test_seq):
    """Run the DTP sanity FSM coverage sequence."""

    def __init__(
        self,
        name: str = "dtp_sanity_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
        random_walks: int = 16,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self.random_walks = random_walks

    def check_all_tap_states_visited(self) -> None:
        """Record that this pass observed every IEEE 1149.1 TAP state."""
        missing = sorted(state.name for state in set(DtpTapState) - self.visited_tap_states)
        self.family_check(
            VISIT_ALL_CHECK_ID,
            "IEEE 1149.1 TAP states visited",
            len(self.visited_tap_states),
            len(DtpTapState),
            context="missing=" + (",".join(missing) or "none"),
        )

    async def record_goto_state(self, target: DtpTapState, context: str) -> None:
        """Record the DUT's exported TAP state against the navigation target."""
        item = await self.sample_observables()
        self.family_check(
            GOTO_CHECK_ID,
            "TAP state after goto",
            item.result,
            int(target),
            context=f"target={target.name} {context}",
        )

    async def check_reset_and_idle(self) -> None:
        """Verify reset, Run-Test/Idle hold, and reset path from Select-IR."""
        self.log.info("Checking TEST_LOGIC_RESET and RUN_TEST_IDLE")
        await self.reset_to_tlr()
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

        for _ in range(3):
            await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

        await self.tms_expect(1, DtpTapState.SELECT_DR_SCAN)
        await self.tms_expect(1, DtpTapState.SELECT_IR_SCAN)
        await self.tms_expect(1, DtpTapState.TEST_LOGIC_RESET)
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

    async def check_dr_path(self) -> None:
        """Visit the DR scan path states and check expected transitions."""
        self.log.info("Checking DR scan path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, DtpTapState.SELECT_DR_SCAN)
        await self.tms_expect(0, DtpTapState.CAPTURE_DR)
        await self.tms_expect(0, DtpTapState.SHIFT_DR)

        for _ in range(3):
            await self.tms_expect(0, DtpTapState.SHIFT_DR)

        await self.tms_expect(1, DtpTapState.EXIT1_DR)
        await self.tms_expect(1, DtpTapState.UPDATE_DR)
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

    async def check_ir_path(self) -> None:
        """Visit the IR scan path states and check expected transitions."""
        self.log.info("Checking IR scan path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, DtpTapState.SELECT_DR_SCAN)
        await self.tms_expect(1, DtpTapState.SELECT_IR_SCAN)
        await self.tms_expect(0, DtpTapState.CAPTURE_IR)
        await self.tms_expect(0, DtpTapState.SHIFT_IR)

        for _ in range(3):
            await self.tms_expect(0, DtpTapState.SHIFT_IR)

        await self.tms_expect(1, DtpTapState.EXIT1_IR)
        await self.tms_expect(1, DtpTapState.UPDATE_IR)
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

    async def check_pause_paths(self) -> None:
        """Visit DR/IR Pause and Exit2 states and check resume transitions."""
        self.log.info("Checking DR pause and EXIT2 path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, DtpTapState.SELECT_DR_SCAN)
        await self.tms_expect(0, DtpTapState.CAPTURE_DR)
        await self.tms_expect(0, DtpTapState.SHIFT_DR)
        await self.tms_expect(1, DtpTapState.EXIT1_DR)
        await self.tms_expect(0, DtpTapState.PAUSE_DR)

        for _ in range(2):
            await self.tms_expect(0, DtpTapState.PAUSE_DR)

        await self.tms_expect(1, DtpTapState.EXIT2_DR)
        await self.tms_expect(0, DtpTapState.SHIFT_DR)
        await self.tms_expect(1, DtpTapState.EXIT1_DR)
        await self.tms_expect(1, DtpTapState.UPDATE_DR)
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

        self.log.info("Checking IR pause and EXIT2 path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, DtpTapState.SELECT_DR_SCAN)
        await self.tms_expect(1, DtpTapState.SELECT_IR_SCAN)
        await self.tms_expect(0, DtpTapState.CAPTURE_IR)
        await self.tms_expect(0, DtpTapState.SHIFT_IR)
        await self.tms_expect(1, DtpTapState.EXIT1_IR)
        await self.tms_expect(0, DtpTapState.PAUSE_IR)

        for _ in range(2):
            await self.tms_expect(0, DtpTapState.PAUSE_IR)

        await self.tms_expect(1, DtpTapState.EXIT2_IR)
        await self.tms_expect(0, DtpTapState.SHIFT_IR)
        await self.tms_expect(1, DtpTapState.EXIT1_IR)
        await self.tms_expect(1, DtpTapState.UPDATE_IR)
        await self.tms_expect(0, DtpTapState.RUN_TEST_IDLE)

    async def check_random_state_navigation(self, rng: random.Random) -> None:
        """Visit TAP states from randomized, non-specific current states."""
        states = list(DtpTapState)
        rng.shuffle(states)

        self.log.info("Checking randomized TAP state navigation")
        for idx, state in enumerate(states, start=1):
            await self.goto_tap_state(state)
            await self.record_goto_state(state, f"shuffled {idx}/{len(states)}")
            await self.random_tms_walk(rng.randint(1, 8), rng=rng)

        for idx in range(1, self.random_walks + 1):
            target = await self.goto_random_tap_state(rng=rng)
            await self.record_goto_state(target, f"walk {idx}/{self.random_walks}")
            await self.random_tms_walk(rng.randint(1, 8), rng=rng)

    async def check_bypass_latency(self, rng: random.Random) -> int:
        """Scan the directed and seeded patterns through BYPASS (IR 0x00).

        Returns how many patterns' one-TCK-delayed image differs from the
        pattern itself, the witness that the delay was observed.
        """
        patterns = [BYPASS_DIRECTED_PATTERN] + [
            self.random_pattern(BYPASS_WIDTH, rng) for _ in range(BYPASS_RANDOM_PATTERNS)
        ]
        delayed_observations = 0
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "BYPASS pattern=0x%016x", pattern)
            await self.check_bypass_delay(DtpJtagInstr.BYPASS_00, pattern, BYPASS_WIDTH)
            expected = self.expected_bypass_tdo(pattern, BYPASS_WIDTH)
            delayed_observations += int(expected != pattern & self.bit_mask(BYPASS_WIDTH))
        return delayed_observations

    async def force_tlr_via_tms(self, checker: OcahJtagChecker) -> None:
        """Hold TMS high for five TCK cycles and record the forced Test-Logic-Reset."""
        start = self.current_tap_state
        start_name = "unknown" if start is None else start.name
        for _ in range(TLR_TMS_ONES):
            await self.tms_expect(1)
        item = await self.sample_observables()
        checker.check_tms_ones_to_tlr(TLR_TMS_ONES, item.result, context=f"from={start_name}")

    async def body(self) -> None:
        checker = await self.attach_family_checker(
            set(REQUIRED_CHECK_IDS),
            # The raw TMS walks visit Shift-DR and Shift-IR on their own, so
            # the pin-level scan monitor would count episodes the sequence
            # never issued as scans.
            use_monitor=False,
        )
        seed = self.scenario_seed
        self.log.info("Using TAP FSM random seed %d", seed)
        rng = random.Random(seed)

        self.log_step(1, "Directed TAP paths: reset and idle, DR, IR, pause legs")
        directed_scenarios = [
            self.check_reset_and_idle,
            self.check_dr_path,
            self.check_ir_path,
            self.check_pause_paths,
        ]
        rng.shuffle(directed_scenarios)
        for scenario in directed_scenarios:
            await scenario()

        self.log_step(2, "Randomized TAP state navigation and walks")
        await self.check_random_state_navigation(rng)
        self.check_all_tap_states_visited()

        self.log_step(3, "BYPASS (IR 0x00) one-TCK TDI-to-TDO delay")
        delayed_observations = await self.check_bypass_latency(self.rng("sanity_bypass"))

        self.log_step(4, "Test-Logic-Reset on five TMS-high cycles")
        await self.force_tlr_via_tms(checker)

        state_checks = sum(
            1 for finding in checker.evidence.findings if finding.check_id == "CHK-TAP-STATE"
        )
        checker.expect_true(
            "CHK-NONVAC",
            len(self.visited_tap_states) == len(DtpTapState)
            and state_checks > 0
            and delayed_observations > 0,
            context=(
                f"states_visited={len(self.visited_tap_states)} "
                f"tms_steps_checked={state_checks} "
                f"bypass_patterns={1 + BYPASS_RANDOM_PATTERNS} "
                f"delayed_observations={delayed_observations}"
            ),
        )
        await self.finalize_family_checker()
