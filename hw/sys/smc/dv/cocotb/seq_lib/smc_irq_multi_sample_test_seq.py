# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_irq_multi_sample_test.

Takes three IRQ observer samples separated by a fixed gap and, at the end,
consumes the collected items: the count must match the stimulus actually
issued, every sample must be resolvable, and the three aggregate readings must
be identical across the gaps (idle stability) ([NO-DUMMY-DEAD-CODE]).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_irq_item import IRQ_SAMPLE_FIELDS, SmcIrqItem, SmcIrqOp

from .smc_base_test_seq import smc_base_test_seq


class smc_irq_multi_sample_test_seq(smc_base_test_seq):
    # Sampling cadence only. This is not a completion sync: nothing is waited
    # *for* here -- the gap exists so the three samples land in different
    # cycles, and the sample itself is the observable ([NO-BLIND-DELAY-SYNC]).
    GAP_REF_CYCLES = 100
    SAMPLE_COUNT = 3

    def __init__(self, name: str = "smc_irq_multi_sample_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcIrqItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        for i in range(self.SAMPLE_COUNT):
            item = SmcIrqItem(f"sample_{i}")
            item.op = SmcIrqOp.SAMPLE
            await self.start_item(item)
            await self.finish_item(item)
            self.samples.append(item)
            if i < self.SAMPLE_COUNT - 1:
                await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)

        # Minimum-activity gate: an empty/short collection is a stimulus defect,
        # never a pass ([NO-ZERO-ACTIVITY-PASS]).
        assert len(self.samples) == self.SAMPLE_COUNT, (
            f"IRQ multi-sample collected {len(self.samples)} samples, expected {self.SAMPLE_COUNT}"
        )
        for item in self.samples:
            assert item.resolvable, f"IRQ sample {item.get_name()} unresolvable (X/Z): {item}"

        # Cross-gap stability: the aggregates observed over the three windows
        # must be identical. The scoreboard already compares each sample against
        # its own exact expectation; this adds the property this test exists for
        # -- that the readings do not move across the gaps.
        first = self.samples[0]
        golden = tuple(getattr(first, f) for f in IRQ_SAMPLE_FIELDS)
        for item in self.samples[1:]:
            got = tuple(getattr(item, f) for f in IRQ_SAMPLE_FIELDS)
            assert got == golden, (
                f"IRQ aggregates changed across a {self.GAP_REF_CYCLES}-ref-cycle "
                f"gap: {first.get_name()} read {dict(zip(IRQ_SAMPLE_FIELDS, golden))}, "
                f"{item.get_name()} read {dict(zip(IRQ_SAMPLE_FIELDS, got))}"
            )
        cocotb.log.info(
            "CHK-IRQ-MULTI-SAMPLE-STABLE: %d resolvable SAMPLEs %d ref cycles apart all read %s",
            len(self.samples),
            self.GAP_REF_CYCLES,
            dict(zip(IRQ_SAMPLE_FIELDS, golden)),
        )
