# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_sanity_test.

Implements the DTP VPLAN sanity scenario: exercise the IEEE 1149.1 TAP finite
state machine by visiting and checking all primary TAP controller states.
"""

from __future__ import annotations

import random

from env.dtp_types import DtpTapState

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq


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
        """Assert that this sanity scenario observed every TAP state."""
        missing = set(DtpTapState) - self.visited_tap_states
        assert not missing, "Not all IEEE 1149.1 TAP states were visited: " + ", ".join(
            sorted(state.name for state in missing)
        )
        self.log.info("All %d IEEE 1149.1 TAP states visited", len(DtpTapState))

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
        for state in states:
            await self.goto_tap_state(state)
            await self.random_tms_walk(rng.randint(1, 8), rng=rng)

        for _ in range(self.random_walks):
            await self.goto_random_tap_state(rng=rng)
            await self.random_tms_walk(rng.randint(1, 8), rng=rng)

    async def body(self) -> None:
        seed = self.scenario_seed
        self.log.info("Using TAP FSM random seed %d", seed)
        rng = random.Random(seed)

        directed_scenarios = [
            self.check_reset_and_idle,
            self.check_dr_path,
            self.check_ir_path,
            self.check_pause_paths,
        ]
        rng.shuffle(directed_scenarios)
        for scenario in directed_scenarios:
            await scenario()

        await self.check_random_state_navigation(rng)
        self.check_all_tap_states_visited()
