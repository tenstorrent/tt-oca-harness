# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_irq_during_powergood_glitch_test.

Property under test: a powergood glitch and the recovery that follows must not
produce a spurious interrupt on any of the three observed aggregates
(``tb_sync_irq`` / ``tb_gpio_irq_any`` / ``tb_uart_irq_any``).

Four things make that claim fail-capable:

* **the glitch is proven to have happened** -- a bounded ``WAIT_STATE`` plus an
  exact mid-glitch ``RAW_SAMPLE`` (``powergood_stable_o==0`` with the
  cold-stable and both primary resets asserted) ride on reset items, so the
  scoreboard owns the verdict. A DUT that ignores ``powergood_i`` fails here
  instead of quietly turning the whole test into a no-op
  ([NO-ALWAYS-PASS-CHECKER]).
* **the window is observed continuously** -- a cycle-accurate ``clk_ref_i``
  watcher runs from before the glitch until after recovery and fails on the
  first resolvable non-zero (or on an unresolvable) IRQ aggregate. Bookend
  samples alone could not catch a transient assert that is gone again by the
  final sample.
* **mid-window SAMPLEs are dispatched** during the glitch hold and while
  recovery is in flight, so the scoreboard books checked (not observed-only)
  IRQ evidence from inside the window as well.
* **recovery is proven, not assumed** -- the recovered idle-IRQ leg is a
  negative check, so it is preceded by a bounded ``WAIT_STATE`` on all five
  reset observables released. Without it, a DUT stuck in reset presents the
  same all-zero IRQ aggregates and passes identically.

  That closes the *reset-chain* half of ``[NEGATIVE-NEEDS-POSITIVE-CONTROL]``
  only. The *probe-liveness* half -- that each aggregate is able to read 1 at all,
  so the zero readings are not those of a tied-off net -- is closed by the
  controls the test declares
  (``probe_positive_controls = ("sync_irq", "uart_irq_any", "gpio_irq_any")``,
  ``seq_lib/smc_probe_positive_control.py``), which run before this scenario and
  credit the ledger the scoreboard consults; the dispatched SAMPLEs below are
  exact-compared rather than booked OBSERVED-ONLY only because of that credit.

Every wait is a bounded poll on a real observable whose expiry fails with the
last observed state; no fixed delay stands in for a completion handshake
([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp
from env.smc_reset_item import SmcResetItem, SmcResetOp

from ._one_shot import _OneShot  # noqa: F401  (re-exported for the test module)
from .smc_base_test_seq import smc_base_test_seq

# tb_top probes of the three interrupt aggregates the IRQ agent samples, keyed
# by the SmcIrqItem field name so the watcher and the scoreboard talk about the
# same signals.
_IRQ_PROBES = {
    "sync_irq": "tb_sync_irq",
    "gpio_irq_any": "tb_gpio_irq_any",
    "uart_irq_any": "tb_uart_irq_any",
}


class smc_irq_during_powergood_glitch_test_seq(smc_base_test_seq):
    # Stimulus quantity: the minimum time powergood_i is held low, in clk_ref_i
    # cycles, enforced in the body -- the mid-glitch SAMPLEs usually take longer
    # than this on their own, and whatever they do not cover is topped up before
    # powergood_i is released. The measured hold is reported in the evidence
    # line, so the width of the observed negative window is stated rather than
    # incidental.
    GLITCH_REF_CYCLES = 8
    # powergood_stable_o is the stretcher output, so the glitch must become
    # visible within a few clk_ref_i edges. Generous ceiling, never the checked
    # quantity -- expiry is a failure.
    GLITCH_EFFECT_BOUND_REF_CYCLES = 64
    # Recovery re-qualifies power-good and walks the cold-reset extender before
    # primary release, which takes a few hundred clk_ref_i edges. Ceiling only.
    RECOVER_BOUND_REF_CYCLES = 2000
    # Mid-window dispatched SAMPLEs and their cadence. The continuous watcher
    # (not this cadence) is what catches a transient assert; these exist so the
    # scoreboard books checked IRQ evidence from inside the window too.
    GLITCH_IRQ_SAMPLES = 2
    RECOVERY_IRQ_SAMPLES = 8
    IRQ_SAMPLE_GAP_REF_CYCLES = 8

    def __init__(self, name: str = "smc_irq_during_powergood_glitch_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.dispatch_irq = None
        self.baseline_irq = None
        self.recovered_irq = None
        self.glitch_irq_samples: list[SmcIrqItem] = []
        self.recovery_irq_samples: list[SmcIrqItem] = []
        self.glitch_effect = None
        self.recovery_wait = None
        # clk_ref_i cycles powergood_i was actually held low (measured by the
        # continuous watcher's own edge count, so it is the same time base the
        # no-spurious-IRQ window is reported in).
        self.glitch_hold_ref_cycles = 0
        # Continuous-observer state.
        self._watch_cycles = 0
        self._watch_violations: list[str] = []
        self._watch_unresolvable: list[str] = []

    # ------------------------------------------------------------------ items --
    async def _irq_sample(self, name: str) -> SmcIrqItem:
        """One IRQ SAMPLE. Expectations default to the idle 0 on every leg."""
        item = SmcIrqItem(name)
        item.op = SmcIrqOp.SAMPLE
        await self.dispatch_irq(item)
        return item

    async def _reset_item(self, name: str, op: SmcResetOp, **expects) -> SmcResetItem:
        item = SmcResetItem(name)
        item.op = op
        for field, value in expects.items():
            setattr(item, field, value)
        await self.dispatch_reset(item)
        return item

    # -------------------------------------------------------------- observer --
    async def _watch_irq(self, dut) -> None:
        """Cycle-accurate observer of the three IRQ aggregates.

        Records rather than raises: the sequence body owns the verdict so the
        diagnostics (and the observed-cycle count that proves the watcher ran)
        are reported together at the end of the window.
        """
        while True:
            await RisingEdge(dut.clk_ref_i)
            self._watch_cycles += 1
            now = get_sim_time("ns")
            for field, probe in _IRQ_PROBES.items():
                raw = getattr(dut, probe).value
                if not raw.is_resolvable:
                    # An interrupt line to the CPU going X/Z is a defect, not a
                    # don't-care, so it is reported as a failure rather than
                    # resolved arbitrarily by int() ([X-AWARE-CHECK]).
                    self._watch_unresolvable.append(f"{probe} unresolvable ({raw}) at {now}ns")
                    continue
                if int(raw) != 0:
                    self._watch_violations.append(f"{probe} asserted ({int(raw)}) at {now}ns")

    def _check_watch(self, label: str) -> None:
        assert self._watch_cycles > 0, (
            f"{label}: the continuous IRQ observer saw 0 clk_ref_i edges -- it "
            f"never ran, so 'no spurious IRQ' is unproven"
        )
        assert not self._watch_unresolvable, (
            f"{label}: IRQ aggregate(s) unresolvable during the "
            f"glitch/recovery window over {self._watch_cycles} clk_ref_i "
            f"cycles: {self._watch_unresolvable[:8]}"
        )
        assert not self._watch_violations, (
            f"{label}: spurious IRQ assertion(s) observed during the "
            f"glitch/recovery window over {self._watch_cycles} clk_ref_i "
            f"cycles: {self._watch_violations[:8]}"
        )

    # ------------------------------------------------------------------ body --
    async def body(self) -> None:
        dut = cocotb.top

        # S1: pre-glitch idle baseline (scoreboard: resolvable + all aggregates 0).
        self.baseline_irq = await self._irq_sample("irq_baseline")

        # S2: arm the continuous observer, then glitch powergood.
        watcher = cocotb.start_soon(self._watch_irq(dut))
        await self._reset_item("pg_lo", SmcResetOp.POWERGOOD_LO)
        hold_start_cycle = self._watch_cycles
        # Bounded proof that the glitch reached the DUT.
        self.glitch_effect = await self._reset_item(
            "pg_glitch_effect",
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.GLITCH_EFFECT_BOUND_REF_CYCLES,
        )

        # S3: IRQ SAMPLEs from inside the glitch hold.
        for i in range(self.GLITCH_IRQ_SAMPLES):
            self.glitch_irq_samples.append(await self._irq_sample(f"irq_mid_glitch_{i}"))
            await ClockCycles(dut.clk_ref_i, self.IRQ_SAMPLE_GAP_REF_CYCLES)

        # Exact gated state while power-good is not stable (SPEC: POR holds the
        # SMC functional resets asserted until power-good is stable).
        await self._reset_item(
            "pg_mid_glitch",
            SmcResetOp.RAW_SAMPLE,
            expect_powergood_stable=0,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )

        # S4: hold the glitch for at least GLITCH_REF_CYCLES clk_ref_i cycles
        # before releasing it, so the observed low window is a stated stimulus
        # quantity and not whatever the mid-glitch SAMPLEs happened to take.
        held = self._watch_cycles - hold_start_cycle
        if held < self.GLITCH_REF_CYCLES:
            await ClockCycles(dut.clk_ref_i, self.GLITCH_REF_CYCLES - held)
        self.glitch_hold_ref_cycles = self._watch_cycles - hold_start_cycle
        assert self.glitch_hold_ref_cycles >= self.GLITCH_REF_CYCLES, (
            f"powergood_i was held low for only "
            f"{self.glitch_hold_ref_cycles} clk_ref_i cycles, below the "
            f"{self.GLITCH_REF_CYCLES}-cycle minimum this test states as its "
            f"glitch width"
        )

        # Release powergood and keep sampling IRQ while recovery is in flight.
        await self._reset_item("pg_hi", SmcResetOp.POWERGOOD_HI)
        for i in range(self.RECOVERY_IRQ_SAMPLES):
            self.recovery_irq_samples.append(await self._irq_sample(f"irq_recovering_{i}"))
            await ClockCycles(dut.clk_ref_i, self.IRQ_SAMPLE_GAP_REF_CYCLES)

        # S5: positive control for the recovered idle-IRQ leg -- prove the DUT
        # really came back (all five reset observables released), bounded.
        self.recovery_wait = await self._reset_item(
            "pg_recovered",
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
            expect_rst_wdt_smc_clk_n=1,
            timeout_ref_cycles=self.RECOVER_BOUND_REF_CYCLES,
        )

        # S6: close the observation window and rule on it.
        watcher.kill()
        self._check_watch("powergood glitch + recovery")

        # S7: post-recovery idle IRQ, now that recovery is proven.
        self.recovered_irq = await self._irq_sample("irq_recovered")

        # Both bookends are consumed: resolvable, and the recovered aggregates
        # equal the pre-glitch baseline. A sample that is stored and never read
        # is not evidence ([NO-DUMMY-DEAD-CODE]).
        for item in (self.baseline_irq, self.recovered_irq):
            assert item.resolvable, f"{item.get_name()} IRQ sample unresolvable (X/Z): {item}"
        base = tuple(getattr(self.baseline_irq, f) for f in IRQ_SAMPLE_FIELDS)
        recovered = tuple(getattr(self.recovered_irq, f) for f in IRQ_SAMPLE_FIELDS)
        assert recovered == base, (
            "IRQ aggregates did not return to their pre-glitch values: baseline "
            f"{dict(zip(IRQ_SAMPLE_FIELDS, base))} vs recovered "
            f"{dict(zip(IRQ_SAMPLE_FIELDS, recovered))}"
        )
        cocotb.log.info(
            "CHK-IRQ-PG-GLITCH-NO-SPURIOUS: glitch observed "
            "(powergood_stable=0, primary resets asserted) after %d ref cycles, "
            "powergood_i held low for %d clk_ref_i cycles (>= the stated %d), "
            "recovery proven after %d ref cycles, %d dispatched SAMPLEs "
            "(1 baseline + %d mid-glitch + %d recovering + 1 recovered) and %d "
            "continuously observed clk_ref_i cycles with every IRQ aggregate "
            "resolvable and 0",
            self.glitch_effect.wait_ref_cycles,
            self.glitch_hold_ref_cycles,
            self.GLITCH_REF_CYCLES,
            self.recovery_wait.wait_ref_cycles,
            2 + len(self.glitch_irq_samples) + len(self.recovery_irq_samples),
            len(self.glitch_irq_samples),
            len(self.recovery_irq_samples),
            self._watch_cycles,
        )
