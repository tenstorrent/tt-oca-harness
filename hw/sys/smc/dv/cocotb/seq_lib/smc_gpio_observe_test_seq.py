# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_gpio_observe_test.

Dispatches the single **reference** SAMPLE of the three ``tb_gpio_*_any``
observability aggregates. ``smc_gpio_observe_test.run_scenario`` reads
``self.sample`` and hands it to
``smc_probe_positive_control.SmcGpioAggregateStabilitySeq``, which dispatches two
further SAMPLEs carrying these three readings as ``expect_<field>`` -- that is
where this testcase's fail-capable DUT compares live (three exact scoreboard
compares per stability sample, plus the sequence-side cross-sample diagnostic).

This leaf therefore owns the *preconditions* of that proof, and asserts them
rather than assuming them:

* the sample reached the scoreboard (a mis-bound analysis port would make every
  later ``expect_*`` compare vacuous);
* the reference readings are defined (0/1) -- an unusable reference cannot be
  the right-hand side of an exact compare.

It emits no ``CHK-`` token. Neither precondition can fail on any RTL
under a 2-state simulator, so a token here would claim checked evidence that the
gates do not provide ([EVIDENCE-TOKEN-CONDITIONAL]); the testcase's evidence
token is ``CHK-GPIO-PAD-BUS-STABLE``, emitted by the stability sequence after
its exact compares pass. No absolute idle level is asserted: these aggregates are
OR-reductions over the whole pad bus (which carries idle-high LSIO pads such as
UART TX), so a specific level is a bus artifact rather than a GPIO property --
see the ``smc_gpio_agent`` module doc, and ``smc_gpio_output_driveback_test`` for
the per-pad level proof.
"""

from __future__ import annotations

from env.smc_gpio_item import SmcGpioItem, SmcGpioOp

from .smc_base_test_seq import smc_base_test_seq


class smc_gpio_observe_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_gpio_observe_test_seq") -> None:
        super().__init__(name)
        # Read by smc_gpio_observe_test.run_scenario as the reference of the
        # SmcGpioAggregateStabilitySeq compares.
        self.sample = None

    async def body(self) -> None:
        sb = self.env.scoreboard
        seen_before = sb.gpio_samples_seen

        item = SmcGpioItem("sample")
        item.op = SmcGpioOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item

        booked = sb.gpio_samples_seen - seen_before
        assert booked == 1, (
            f"GPIO observe: scoreboard booked {booked} SAMPLE item(s), expected "
            f"1 -- the reference sample never reached the scoreboard, so the "
            f"stability compares that consume it would be vacuous: {item}"
        )
        assert item.resolvable, (
            f"GPIO observe: the reference sample is not resolvable (X/Z), so it "
            f"cannot be the expectation of the stability compares: {item}"
        )
