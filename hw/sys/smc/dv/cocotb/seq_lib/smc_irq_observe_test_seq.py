# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_irq_observe_test.

One IRQ SAMPLE of the three ``tb_top`` interrupt aggregates, consumed into the
only property this leaf can honestly claim: **every aggregate reads its idle 0
and every one of the three probes carries a same-run liveness credit**, so the
scoreboard exact-compared all three legs instead of booking them OBSERVED-ONLY.

The scoreboard *silently* downgrades an uncredited idle ``== 0`` leg to
``OBSERVED-ONLY (NOT checked evidence)`` rather than failing, so the gate below
requires the credit explicitly. The credits come from the passive ledger in
``env/smc_probe_liveness.py``, which is fed by a DUT observation (the probe seen
at 1), so requiring them is DUT-sensitive: a stuck-at-0 / undriven / mis-bound
aggregate fails here.

``item.resolvable`` is **not** presented as this testcase's check: on a 2-state
Verilator build ``value.is_resolvable`` cannot be False, so it has no FAIL-ON
path there.
"""

from __future__ import annotations

import cocotb
from env.smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp
from env.smc_probe_liveness import probe_alive, probe_evidence

from .smc_base_test_seq import smc_base_test_seq

# Idle expectation of each aggregate for a test that programs no interrupt
# source: the same default `SmcIrqItem.expected()` applies when `expect_<field>`
# is left None, restated here so the sequence-side gate names the value it
# requires instead of re-deriving it from the item.
IRQ_IDLE_LEVEL = 0


class smc_irq_observe_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_irq_observe_test_seq") -> None:
        super().__init__(name)
        self.sample = None

    async def body(self) -> None:
        sb = self.env.scoreboard
        seen_before = sb.irq_samples_seen

        cocotb.log.info(
            "STEP S1: INSTRUMENTATION-ONLY one SmcIrqItem SAMPLE "
            "(tb_sync_irq/tb_gpio_irq_any/tb_uart_irq_any)"
        )
        item = SmcIrqItem("sample")
        item.op = SmcIrqOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)
        self.sample = item

        # The sample is evidence only if it actually reached the scoreboard --
        # a mis-bound analysis port would make every compare below vacuous.
        booked = sb.irq_samples_seen - seen_before
        assert booked == 1, (
            f"IRQ observe: scoreboard booked {booked} SAMPLE item(s), expected "
            f"1 (a mis-bound analysis port would make the idle compares "
            f"vacuous): {self.sample}"
        )

        # Every leg must be *checked*, not observed-only: require a same-run
        # liveness credit for each probe ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        uncredited = [f for f in IRQ_SAMPLE_FIELDS if not probe_alive(f)]
        assert not uncredited, (
            "IRQ observe: no same-run liveness credit for "
            + ", ".join(f"{f} ({probe_evidence(f)})" for f in uncredited)
            + " -- the scoreboard books those idle legs OBSERVED-ONLY, so this "
            "testcase would report an all-zero read from a possibly dead probe "
            "as evidence. The producing controls are declared by the test as "
            'probe_positive_controls = ("sync_irq", "uart_irq_any", '
            '"gpio_irq_any").'
        )

        # Idle contract, restated where the diagnostic can name the sample: the
        # aggregates must read 0 with no interrupt source programmed. Fail-capable
        # because the credits above prove each probe can also read 1.
        for field in IRQ_SAMPLE_FIELDS:
            got = getattr(self.sample, field)
            assert got == IRQ_IDLE_LEVEL, (
                f"tb_{field} read {got}, expected the idle {IRQ_IDLE_LEVEL} "
                f"with no interrupt source programmed in this test "
                f"(probe liveness: {probe_evidence(field)}): {self.sample}"
            )

        cocotb.log.info(
            "CHK-IRQ-OBSERVE-IDLE-CHECKED: all %d IRQ aggregates read the idle "
            "%d on a scoreboard-booked SAMPLE, and each carries a same-run "
            "liveness credit, so every leg was exact-compared rather than "
            "OBSERVED-ONLY (%s)",
            len(IRQ_SAMPLE_FIELDS),
            IRQ_IDLE_LEVEL,
            "; ".join(f"{f}: {probe_evidence(f)}" for f in IRQ_SAMPLE_FIELDS),
        )
