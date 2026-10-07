# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_sanity_test.

Implements the DTP VPLAN sanity scenario: exercise the IEEE 1149.1 TAP finite
state machine by visiting and checking all sixteen TAP controller states and
all 32 legal transitions, scan patterns through BYPASS, read IDCODE through
the instruction Test-Logic-Reset selects, and force Test-Logic-Reset with five
TMS-high cycles. Each pass starts from power-on and system reset with every
debug disable held fail-closed, since the random walks shift random TDI into
whatever instruction they load. Every IR and DR scan the sequence issues is
one new Shift-x visit of the DUT's exported TAP state, as long as the width
driven. Every comparison lands as named ``CHK-*`` evidence through the family
checker, finalized once per pass. The SV-UVM twin is
``uvm/seq_lib/dtp_sanity_test_seq.svh``.
"""

from __future__ import annotations

import random

from env.dtp_dbg_disable import DBG_DISABLE_FIELDS
from env.dtp_tap_device import DTP_DEFAULT_IDCODE
from env.dtp_types import DtpJtagInstr
from ocah_jtag_vip import TLR_TMS_ONES, OcahJtagChecker, OcahJtagState
from ocah_lib import OcahKnobs

from .dtp_jtag_base_test_seq import dtp_jtag_base_test_seq

VISIT_ALL_CHECK_ID = "CHK-TAP-VISIT-ALL"
GOTO_CHECK_ID = "CHK-TAP-GOTO"
# CHK-TAP-RESET-TLR and CHK-TAP-STATE come from the attached checker on every
# TAP reset and raw TMS step, CHK-SCAN-IR-LEN and CHK-SCAN-DR-LEN from every
# issued scan; the others are this sequence's own records.
REQUIRED_CHECK_IDS: frozenset[str] = frozenset(
    {
        "CHK-TAP-RESET-TLR",
        "CHK-TAP-STATE",
        GOTO_CHECK_ID,
        "CHK-TAP-TLR-TMS5",
        VISIT_ALL_CHECK_ID,
        "CHK-IR-DECODE",
        "CHK-BYPASS-LATENCY",
        "CHK-TAP-TLR-IDCODE",
        "CHK-IDCODE-RAW",
        "CHK-IDCODE-STABLE",
        "CHK-IDCODE-MARKER",
        "CHK-SCAN-IR-LEN",
        "CHK-SCAN-DR-LEN",
        "CHK-NONVAC",
    }
)
# Every IEEE 1149.1 state has one transition for each TMS value.
TAP_ARC_COUNT = 2 * len(OcahJtagState)
# From Test-Logic-Reset this walk takes all 32 legal transitions, visits all
# sixteen states, and returns to Test-Logic-Reset through five TMS-high
# cycles; the SV-UVM twin drives the same bits.
# fmt: off
DETERMINISTIC_WALK_TMS: tuple[int, ...] = (
    # TLR self-loop, RTI, full DR leg with the pause/exit2 re-shift
    1, 0, 0, 1, 0, 0, 0, 1, 0, 0,
    1, 0, 1, 1, 1, 0, 1, 1, 0, 1,
    # full IR leg with the pause/exit2 re-shift, Select-IR -> TLR
    1, 0, 0, 0, 1, 0, 0, 1, 0, 1,
    1, 1, 1, 0, 1, 1, 0, 1, 1, 1,
    # Exit2-DR -> Update-DR
    0, 1, 0, 0, 1, 0, 1, 1,
    # Exit2-IR -> Update-IR
    1, 1, 0, 0, 1, 0, 1, 1,
    # back to TLR through five TMS-high cycles
    0, 1, 1, 1, 1, 1,
)
# fmt: on
BYPASS_WIDTH = 64
# Directed pattern whose one-TCK-delayed image differs from a pass-through.
BYPASS_DIRECTED_PATTERN = 0xA5A5_5A5A_C3C3_3C3C
BYPASS_RANDOM_PATTERNS = 2
IDCODE_WIDTH = 32
IDCODE_MASK = 0xFFFF_FFFF
IDCODE_READS = 3
# Reset-ladder pulse widths: power-on reset in TCK periods, system reset in
# system-clock cycles.
POR_PULSE_TCK_PERIODS = 5
SYS_RESET_PULSE_CYCLES = 5


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

    def check_all_tap_states_visited(self, checker: OcahJtagChecker) -> None:
        """Record that this pass observed every IEEE 1149.1 TAP state and legal transition."""
        missing = sorted(state.name for state in set(OcahJtagState) - self.visited_tap_states)
        checker.expect_equal(
            VISIT_ALL_CHECK_ID,
            len(self.visited_tap_states),
            len(OcahJtagState),
            context="IEEE 1149.1 TAP states visited missing=" + (",".join(missing) or "none"),
        )
        all_arcs = {(state, tms) for state in OcahJtagState for tms in (0, 1)}
        missing_arcs = sorted(all_arcs - self.visited_tap_arcs)
        checker.expect_equal(
            VISIT_ALL_CHECK_ID,
            len(self.visited_tap_arcs),
            TAP_ARC_COUNT,
            context="IEEE 1149.1 legal TAP transitions taken missing="
            + (",".join(f"{state.name}/tms={tms}" for state, tms in missing_arcs) or "none"),
        )

    async def record_goto_state(self, target: OcahJtagState, context: str) -> None:
        """Record the DUT's exported TAP state against the navigation target."""
        item = await self.sample_observables()
        self.family_check(
            GOTO_CHECK_ID,
            "TAP state after goto",
            item.result,
            int(target),
            context=f"target={target.name} {context}",
        )

    async def reset_ladder(self) -> None:
        """Pulse power-on and system reset, hold every debug disable fail-closed, reset the TAP."""
        item = await self.pulse_por(cycles=POR_PULSE_TCK_PERIODS)
        self.record_tap_state(item.result, OcahJtagState.TEST_LOGIC_RESET)
        await self.pulse_system_reset(cycles=SYS_RESET_PULSE_CYCLES)
        await self.set_dbg_disable_vector({name: 1 for name in DBG_DISABLE_FIELDS})
        await self.reset_to_tlr()

    async def run_deterministic_walk(self) -> None:
        """Walk the fixed TMS sequence that takes all 32 legal transitions from TLR."""
        self.log.info(
            "Deterministic FSM walk: %d TMS steps for 32-transition closure",
            len(DETERMINISTIC_WALK_TMS),
        )
        assert self.current_tap_state is OcahJtagState.TEST_LOGIC_RESET
        for tms in DETERMINISTIC_WALK_TMS:
            await self.tms_expect(tms)
        assert self.current_tap_state is OcahJtagState.TEST_LOGIC_RESET

    async def check_reset_and_idle(self) -> None:
        """Verify reset, Run-Test/Idle hold, and reset path from Select-IR."""
        self.log.info("Checking TEST_LOGIC_RESET and RUN_TEST_IDLE")
        await self.reset_to_tlr()
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

        for _ in range(3):
            await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

        await self.tms_expect(1, OcahJtagState.SELECT_DR_SCAN)
        await self.tms_expect(1, OcahJtagState.SELECT_IR_SCAN)
        await self.tms_expect(1, OcahJtagState.TEST_LOGIC_RESET)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

    async def check_dr_path(self) -> None:
        """Visit the DR scan path states and check expected transitions."""
        self.log.info("Checking DR scan path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, OcahJtagState.SELECT_DR_SCAN)
        await self.tms_expect(0, OcahJtagState.CAPTURE_DR)
        await self.tms_expect(0, OcahJtagState.SHIFT_DR)

        for _ in range(3):
            await self.tms_expect(0, OcahJtagState.SHIFT_DR)

        await self.tms_expect(1, OcahJtagState.EXIT1_DR)
        await self.tms_expect(1, OcahJtagState.UPDATE_DR)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

    async def check_ir_path(self) -> None:
        """Visit the IR scan path states and check expected transitions."""
        self.log.info("Checking IR scan path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, OcahJtagState.SELECT_DR_SCAN)
        await self.tms_expect(1, OcahJtagState.SELECT_IR_SCAN)
        await self.tms_expect(0, OcahJtagState.CAPTURE_IR)
        await self.tms_expect(0, OcahJtagState.SHIFT_IR)

        for _ in range(3):
            await self.tms_expect(0, OcahJtagState.SHIFT_IR)

        await self.tms_expect(1, OcahJtagState.EXIT1_IR)
        await self.tms_expect(1, OcahJtagState.UPDATE_IR)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

    async def check_pause_paths(self) -> None:
        """Visit DR/IR Pause and Exit2 states and check resume transitions."""
        self.log.info("Checking DR pause and EXIT2 path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, OcahJtagState.SELECT_DR_SCAN)
        await self.tms_expect(0, OcahJtagState.CAPTURE_DR)
        await self.tms_expect(0, OcahJtagState.SHIFT_DR)
        await self.tms_expect(1, OcahJtagState.EXIT1_DR)
        await self.tms_expect(0, OcahJtagState.PAUSE_DR)

        for _ in range(2):
            await self.tms_expect(0, OcahJtagState.PAUSE_DR)

        await self.tms_expect(1, OcahJtagState.EXIT2_DR)
        await self.tms_expect(0, OcahJtagState.SHIFT_DR)
        await self.tms_expect(1, OcahJtagState.EXIT1_DR)
        await self.tms_expect(1, OcahJtagState.UPDATE_DR)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

        self.log.info("Checking IR pause and EXIT2 path")
        await self.goto_run_test_idle()
        await self.tms_expect(1, OcahJtagState.SELECT_DR_SCAN)
        await self.tms_expect(1, OcahJtagState.SELECT_IR_SCAN)
        await self.tms_expect(0, OcahJtagState.CAPTURE_IR)
        await self.tms_expect(0, OcahJtagState.SHIFT_IR)
        await self.tms_expect(1, OcahJtagState.EXIT1_IR)
        await self.tms_expect(0, OcahJtagState.PAUSE_IR)

        for _ in range(2):
            await self.tms_expect(0, OcahJtagState.PAUSE_IR)

        await self.tms_expect(1, OcahJtagState.EXIT2_IR)
        await self.tms_expect(0, OcahJtagState.SHIFT_IR)
        await self.tms_expect(1, OcahJtagState.EXIT1_IR)
        await self.tms_expect(1, OcahJtagState.UPDATE_IR)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)

    async def check_random_state_navigation(self, rng: random.Random) -> None:
        """Visit TAP states from randomized, non-specific current states.

        The random walks between the targeted hops also shift random TDI.
        """
        states = list(OcahJtagState)
        rng.shuffle(states)

        self.log.info("Checking randomized TAP state navigation")
        for idx, state in enumerate(states, start=1):
            await self.goto_tap_state(state)
            await self.record_goto_state(state, f"shuffled {idx}/{len(states)}")
            await self.random_tms_walk(rng.randint(1, 8), rng=rng, random_tdi=True)

        for idx in range(1, self.random_walks + 1):
            target = await self.goto_random_tap_state(rng=rng)
            await self.record_goto_state(target, f"walk {idx}/{self.random_walks}")
            await self.random_tms_walk(rng.randint(1, 8), rng=rng, random_tdi=True)

    async def check_bypass_latency(
        self, rng: random.Random, checker: OcahJtagChecker
    ) -> tuple[int, int]:
        """Load BYPASS (IR 0x00), then scan the directed and seeded patterns through it.

        Returns how many patterns were scanned, and how many of them returned
        their one-TCK-delayed image where that image differs from the pattern
        itself, the witness that the DUT delayed TDI.
        """
        patterns = [BYPASS_DIRECTED_PATTERN] + [
            self.random_pattern(BYPASS_WIDTH, rng) for _ in range(BYPASS_RANDOM_PATTERNS)
        ]
        await self.load_ir(DtpJtagInstr.BYPASS_00)
        await self.expect_decoded_instruction(DtpJtagInstr.BYPASS_00)
        delayed_observations = 0
        for idx, pattern in enumerate(patterns, start=1):
            self.log_iteration(idx, len(patterns), "BYPASS pattern=0x%016x", pattern)
            item = await self.shift_dr(pattern, BYPASS_WIDTH)
            checker.check_bypass_latency(
                item.result,
                pattern=pattern,
                width=BYPASS_WIDTH,
                instruction=int(DtpJtagInstr.BYPASS_00),
            )
            observed = item.result & self.bit_mask(BYPASS_WIDTH)
            expected = self.expected_bypass_tdo(pattern, BYPASS_WIDTH)
            delayed_observations += int(observed == expected and expected != pattern)
        return len(patterns), delayed_observations

    async def run_idcode_checks(self, checker: OcahJtagChecker) -> None:
        """Test-Logic-Reset selects IDCODE, and reads across IR churn are stable.

        DTP_JTAG_TAP_CHECKER_NEGATIVE=1 is the documented negative-validation
        hook: the TAP reference model is desynced to Test-Logic-Reset while
        the TAP sits in Run-Test/Idle, whose TMS=1 successor differs, so the
        first step of the TMS-high walk must produce a CHK-TAP-STATE FAIL.
        """
        if OcahKnobs.is_set("DTP_JTAG_TAP_CHECKER_NEGATIVE"):
            self.log.warning(
                "NEGATIVE VALIDATION: desyncing TAP reference model to "
                "TEST_LOGIC_RESET before the TMS-high walk from %s",
                self.current_tap_state,
            )
            checker.sync_state(OcahJtagState.TEST_LOGIC_RESET)
        await self.force_tlr_via_tms(checker)
        await self.tms_expect(0, OcahJtagState.RUN_TEST_IDLE)
        item = await self.shift_dr(0, IDCODE_WIDTH)
        checker.expect_equal(
            "CHK-TAP-TLR-IDCODE",
            item.result & IDCODE_MASK,
            DTP_DEFAULT_IDCODE,
            context="DR scan after TLR, no IR load",
        )
        reads: list[int] = []
        for read in range(IDCODE_READS):
            if read > 0:
                await self.load_ir(DtpJtagInstr.BYPASS_00)
            await self.load_ir(DtpJtagInstr.IDCODE)
            item = await self.shift_dr(0, IDCODE_WIDTH)
            reads.append(item.result & IDCODE_MASK)
            checker.expect_equal(
                "CHK-IDCODE-RAW",
                reads[-1],
                DTP_DEFAULT_IDCODE,
                context=f"read={read + 1}/{IDCODE_READS}",
            )
        checker.expect_true(
            "CHK-IDCODE-STABLE",
            len(set(reads)) == 1,
            context=f"reads={len(reads)} values=" + ",".join(f"0x{value:08x}" for value in reads),
        )
        checker.expect_equal(
            "CHK-IDCODE-MARKER", reads[0] & 0x1, 1, context=f"raw=0x{reads[0]:08x} bit=0"
        )

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
            # the count-exact scan cross-check would count episodes the
            # sequence never issued as scans; op_scan_len judges each issued
            # scan on its own.
            use_monitor=False,
            op_scan_len=True,
        )
        seed = self.scenario_seed
        self.log.info("Using TAP FSM random seed %d", seed)
        rng = random.Random(seed)

        self.log_step(1, "Power-on and system reset, fail-closed debug disables, TAP reset")
        await self.reset_ladder()

        self.log_step(2, "Fixed TMS walk over all 32 legal TAP transitions")
        await self.run_deterministic_walk()

        self.log_step(3, "Directed TAP paths: reset and idle, DR, IR, pause legs")
        directed_scenarios = [
            self.check_reset_and_idle,
            self.check_dr_path,
            self.check_ir_path,
            self.check_pause_paths,
        ]
        rng.shuffle(directed_scenarios)
        for scenario in directed_scenarios:
            await scenario()

        self.log_step(4, "BYPASS (IR 0x00) one-TCK TDI-to-TDO delay")
        bypass_patterns, delayed_observations = await self.check_bypass_latency(
            self.rng("sanity_bypass"), checker
        )

        self.log_step(5, "Test-Logic-Reset selects IDCODE; IDCODE reads are stable")
        await self.run_idcode_checks(checker)

        self.log_step(6, "Randomized TAP state navigation and walks with random TDI")
        await self.check_random_state_navigation(rng)
        self.check_all_tap_states_visited(checker)

        self.log_step(7, "Test-Logic-Reset on five TMS-high cycles")
        await self.force_tlr_via_tms(checker)

        checker.expect_true(
            "CHK-NONVAC",
            bypass_patterns >= 1 + BYPASS_RANDOM_PATTERNS and delayed_observations > 0,
            context=(
                f"bypass_patterns={bypass_patterns} delayed_observations={delayed_observations}"
            ),
        )
        await self.finalize_family_checker()
