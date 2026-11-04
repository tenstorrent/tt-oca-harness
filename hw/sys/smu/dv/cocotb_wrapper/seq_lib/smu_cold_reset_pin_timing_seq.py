# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_cold_reset_pin_timing_test. No Force.

``hw/sys/smu/doc/port_table.adoc`` (the ``rst_cold_ni`` row of the SMU port
declaration): assertion and deassertion are synchronous to ``clk_ref_i`` and
do not propagate while that clock is stopped; assertion is de-glitched for 32
cycles. The outputs observed are the stable cold reset
``rst_cold_stable_ref_clk_no`` and the SMC primary reset
``rst_primary_smc_clk_no``; ``powergood_i`` stays high throughout.

A pinned 31-``clk_ref`` low pulse, driven right after a ``clk_ref`` edge, and
a pulse of a width drawn from the seed below 32 leave both outputs at 1 on
every ``clk_ref`` sample during the pulse and the 128 after it. A hold drawn
from the seed, 32 to 94 ``clk_ref`` past the observed assertion, asserts the
stable cold reset no earlier than 32 ``clk_ref`` after the pin fell and no
later than 33 (the 32 samples plus the observation), the primary reset on
that sample or the next, keeps the stable reset low on every ``clk_ref``
sample through the hold, and both outputs return after the release. With
``clk_ref_i`` held, the pin driven low for more ``clk_smu_i`` cycles than the
32 samples would take with the clock running leaves both outputs at 1 on
every ``clk_smu_i`` sample; once the clock restarts the stable reset falls 32
to 33 ``clk_ref`` later and both outputs return after the release.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from seq_lib.smu_tb_pins import cold_stable_reset, smc_primary_reset

# port_table.adoc rst_cold_ni: assertion is de-glitched for 32 clk_ref_i cycles.
DEGLITCH_SAMPLES = 32
PINNED_PULSE = DEGLITCH_SAMPLES - 1
# The observation of the stable output adds at most one clk_ref to the 32 samples.
ASSERT_OBS_SLACK = 1
ASSERT_BOUND_REF_CYCLES = 128
HOLD_PAST_ASSERT_MIN = 32
HOLD_PAST_ASSERT_MAX = ASSERT_BOUND_REF_CYCLES - 1 - (DEGLITCH_SAMPLES + ASSERT_OBS_SLACK)
# Deassertion is held for 255 clk_ref and the SMC synchronisers follow; the
# release wait is bounded well above both.
RELEASE_BOUND_REF_CYCLES = 4096
# With clk_ref_i held, the pin is kept low for this many de-glitch windows,
# in clk_smu_i cycles at the ratio of the two periods.
CLOCK_STOP_DEGLITCH_WINDOWS = 4
CLOCK_STOP_MIN_SMU_CYCLES = 256
EVIDENCE_DEGLITCH = "CHK-SMU-COLD-PIN-DEGLITCH"
EVIDENCE_CLKSTOP = "CHK-SMU-COLD-NO-PROPAGATE-CLKSTOP"


class smu_cold_reset_pin_timing_seq:
    """The cold reset pin's de-glitch and its silence while clk_ref_i is held."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        self.pulse = self.rng.randint(1, DEGLITCH_SAMPLES - 1)
        self.past = self.rng.randint(HOLD_PAST_ASSERT_MIN, HOLD_PAST_ASSERT_MAX)
        self.drawn = f"drawn pulse_width={self.pulse} past_assert={self.past}"
        self.stable = cold_stable_reset(self.dut)
        self.primary = smc_primary_reset(self.dut)

    def _bit(self, handle, name: str) -> int:
        val = handle.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    def _levels(self) -> tuple[int, int]:
        return (
            self._bit(self.stable, "rst_cold_stable_ref_clk_no"),
            self._bit(self.primary, "rst_primary_smc_clk_no"),
        )

    async def _wait_both(self, level: int, bound: int, what: str) -> int:
        """clk_ref edges until both outputs read ``level``; raise at the bound."""
        for cycle in range(bound):
            if self._levels() == (level, level):
                return cycle
            await RisingEdge(self.dut.clk_ref_i)
        raise AssertionError(
            f"TIMEOUT {what}: outputs {self._levels()} never both read {level} within "
            f"{bound} clk_ref"
        )

    async def _pulse(self, width: int) -> tuple[int, int, int]:
        """Drive the pin low for ``width`` clk_ref; count pin-low and output-low samples.

        The outputs are counted through 128 clk_ref after the release; the pin
        samples show the pulse reached ``rst_cold_ni`` for exactly ``width`` edges.
        """
        dut = self.dut
        dut.rst_cold_ni.value = 0
        pin_low = 0
        low = [0, 0]
        for cycle in range(width + ASSERT_BOUND_REF_CYCLES):
            if cycle == width:
                dut.rst_cold_ni.value = 1
            await RisingEdge(dut.clk_ref_i)
            pin_low += 1 - self._bit(dut.rst_cold_ni, "rst_cold_ni")
            stable, primary = self._levels()
            low[0] += 1 - stable
            low[1] += 1 - primary
        return pin_low, low[0], low[1]

    async def _release_and_reboot(self, what: str) -> tuple[int, int]:
        """Release the pin and wait for the stable and primary resets to return."""
        dut = self.dut
        dut.rst_cold_ni.value = 1
        stable_after = 0
        for stable_after in range(RELEASE_BOUND_REF_CYCLES):
            if self._bit(self.stable, "rst_cold_stable_ref_clk_no"):
                break
            await RisingEdge(dut.clk_ref_i)
        else:
            raise AssertionError(f"TIMEOUT {what}: the stable cold reset never released")
        both_after = await self._wait_both(1, RELEASE_BOUND_REF_CYCLES, f"{what} primary release")
        self.log.info(
            "OBSERVATION %s: stable cold reset released %d clk_ref after the pin, both outputs "
            "released %d clk_ref later",
            what,
            stable_after,
            both_after,
        )
        return stable_after, both_after

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        drawn = self.drawn
        self.log.info(
            "SEED: RANDOM_SEED=%d %s; pinned pulse_width=%d first", self.seed, drawn, PINNED_PULSE
        )
        await self.cfg.reset_done.wait()
        sb.expect_eq(
            "the stable cold reset and the SMC primary reset read 1 before the pin is driven",
            self._levels(),
            (1, 1),
            evidence=EVIDENCE_DEGLITCH,
        )

        # S1: pulses below the de-glitcher, each driven right after a clk_ref edge.
        await RisingEdge(dut.clk_ref_i)
        pinned = await self._pulse(PINNED_PULSE)
        sb.expect_eq(
            f"a {PINNED_PULSE}-clk_ref low pulse on rst_cold_ni driven at a clk_ref edge (pin "
            f"read low on {pinned[0]} edges) leaves the stable cold reset and the SMC primary "
            "reset at 1 on every clk_ref sample during the pulse and the "
            f"{ASSERT_BOUND_REF_CYCLES} after it (low samples stable/primary {pinned[1:]}) "
            f"pinned pulse_width={PINNED_PULSE}",
            pinned,
            (PINNED_PULSE, 0, 0),
            evidence=EVIDENCE_DEGLITCH,
        )
        await RisingEdge(dut.clk_ref_i)
        drawn_low = await self._pulse(self.pulse)
        sb.expect_eq(
            f"a {self.pulse}-clk_ref low pulse on rst_cold_ni (pin read low on {drawn_low[0]} "
            "edges) leaves both outputs at 1 on every clk_ref sample during the pulse and the "
            f"{ASSERT_BOUND_REF_CYCLES} after it (low samples stable/primary {drawn_low[1:]}) "
            f"{drawn}",
            drawn_low,
            (self.pulse, 0, 0),
            evidence=EVIDENCE_DEGLITCH,
        )

        # S2: a hold above the de-glitcher asserts within 32 to 33 clk_ref.
        await RisingEdge(dut.clk_ref_i)
        dut.rst_cold_ni.value = 0
        held = 0
        asserted_after = None
        primary_after = None
        stable_low_held = 0
        while True:
            stable, primary = self._levels()
            if asserted_after is None:
                if stable == 0:
                    asserted_after = held
            else:
                stable_low_held += 1 - stable
            if primary_after is None and primary == 0:
                primary_after = held
            if asserted_after is not None and held >= asserted_after + self.past:
                break
            if asserted_after is None and held >= ASSERT_BOUND_REF_CYCLES:
                raise AssertionError(
                    f"TIMEOUT cold reset assert: the stable cold reset never read 0 within "
                    f"{ASSERT_BOUND_REF_CYCLES} clk_ref"
                )
            await RisingEdge(dut.clk_ref_i)
            held += 1
        self.log.info(
            "OBSERVATION the pin was held low %d clk_ref: stable cold reset asserted after %d, "
            "SMC primary reset after %s %s",
            held,
            asserted_after,
            primary_after,
            drawn,
        )
        sb.expect_eq(
            f"the held pin asserts the stable cold reset no earlier than {DEGLITCH_SAMPLES} "
            f"clk_ref, the de-glitcher's samples, and no later than "
            f"{DEGLITCH_SAMPLES + ASSERT_OBS_SLACK} (at {asserted_after}), the SMC primary reset "
            f"on that sample or the next (at {primary_after}), and keeps the stable reset low on "
            f"every clk_ref sample through the {held - asserted_after}-clk_ref hold {drawn}",
            (
                DEGLITCH_SAMPLES <= asserted_after <= DEGLITCH_SAMPLES + ASSERT_OBS_SLACK,
                primary_after is not None and asserted_after <= primary_after <= asserted_after + 1,
                stable_low_held,
            ),
            (True, True, held - asserted_after),
            evidence=EVIDENCE_DEGLITCH,
        )
        await self._release_and_reboot("after the hold")
        sb.expect_eq(
            "the stable cold reset and the SMC primary reset read 1 again after the hold",
            self._levels(),
            (1, 1),
            evidence=EVIDENCE_DEGLITCH,
        )

        # S3: the pin low while clk_ref_i is held.
        ratio = self.cfg.ref_clk_period_ns / self.cfg.smu_clk_period_ns
        stop_cycles = max(
            CLOCK_STOP_MIN_SMU_CYCLES,
            int(CLOCK_STOP_DEGLITCH_WINDOWS * DEGLITCH_SAMPLES * ratio) + 1,
        )
        clock = self.test.clocks["clk_ref_i"]
        await FallingEdge(dut.clk_ref_i)
        clock.stop()
        dut.rst_cold_ni.value = 0
        # A clk_smu_i edge in the same time step as the clk_ref_i falling edge
        # samples the pin before the deposit lands; the count starts after it.
        await RisingEdge(dut.clk_smu_i)
        low = [0, 0]
        pin_low = 0
        ref_edges = 0
        prev_ref = self._bit(dut.clk_ref_i, "clk_ref_i")
        for _ in range(stop_cycles):
            await RisingEdge(dut.clk_smu_i)
            ref = self._bit(dut.clk_ref_i, "clk_ref_i")
            ref_edges += ref and not prev_ref
            prev_ref = ref
            pin_low += 1 - self._bit(dut.rst_cold_ni, "rst_cold_ni")
            stable, primary = self._levels()
            low[0] += 1 - stable
            low[1] += 1 - primary
        clock.start(start_high=False)
        fell_after = 0
        for fell_after in range(1, ASSERT_BOUND_REF_CYCLES + 1):
            await RisingEdge(dut.clk_ref_i)
            if self._bit(self.stable, "rst_cold_stable_ref_clk_no") == 0:
                break
        else:
            raise AssertionError(
                f"TIMEOUT clock restart: the stable cold reset never read 0 within "
                f"{ASSERT_BOUND_REF_CYCLES} clk_ref of the restart"
            )
        self.log.info(
            "CHK-SMU-COLD-NO-PROPAGATE-CLKSTOP: clk_ref_i held for %d clk_smu_i (%d clk_ref "
            "edges seen) with rst_cold_ni read low on %d of them: low samples stable/primary %s; "
            "the stable cold reset fell %d clk_ref after the restart",
            stop_cycles,
            ref_edges,
            pin_low,
            low,
            fell_after,
        )
        sb.expect_eq(
            f"CHK-SMU-COLD-NO-PROPAGATE-CLKSTOP with clk_ref_i held for {stop_cycles} clk_smu_i "
            f"and rst_cold_ni read low on every one of them ({pin_low}), the stable cold reset "
            f"and the SMC primary reset read 1 on every clk_smu_i sample (low samples "
            f"{tuple(low)}, clk_ref edges {ref_edges}); after the restart the stable cold reset "
            f"falls {DEGLITCH_SAMPLES} to {DEGLITCH_SAMPLES + ASSERT_OBS_SLACK} clk_ref later "
            f"(at {fell_after})",
            (
                pin_low,
                tuple(low),
                ref_edges,
                DEGLITCH_SAMPLES <= fell_after <= DEGLITCH_SAMPLES + ASSERT_OBS_SLACK,
            ),
            (stop_cycles, (0, 0), 0, True),
            evidence=EVIDENCE_CLKSTOP,
        )
        await self._release_and_reboot("after the clock restart")
        sb.expect_eq(
            "the stable cold reset and the SMC primary reset read 1 again after the restart",
            self._levels(),
            (1, 1),
            evidence=EVIDENCE_CLKSTOP,
        )
