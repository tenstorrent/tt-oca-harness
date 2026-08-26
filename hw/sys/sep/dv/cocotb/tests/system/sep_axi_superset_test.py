# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI channel-timing superset: every legal write ordering must land.

no_cpu / +skip_fuse_sense. Walks write order (AW-first, W-first, same-cycle)
crossed with transfer size (1B, 2B, 4B) -- nine cells, all nine on every seed.
The seed varies the staged data and the stall depth, never which cell runs.

CHK-ORDER: AXI write address and write data are independent channels with no
ordering requirement between them (IHI 0022 A3.3), so all three orderings are
legal stimulus and every one must leave the written value in the register. The
cell primes the word with the complement first, so a write that never lands
reads back as the prime rather than looking plausible.

This is the class of defect a response check cannot see: a slave that latches
a pending-write flag on AW accept and consumes it on W accept returns OKAY
while dropping the data, and may then misapply the stale flag to the next
write to any register in the block.

CHK-COVERAGE: the cell tally is logged, including any cell that could not run
and why. A dropped cell is named rather than absorbed, so partial coverage
never reads as a full sweep.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_axi_superset_seq import (
    SIZE_BYTES,
    SepAxiSuperset,
    SepAxiSupersetCfg,
)


@pyuvm.test()
class sep_axi_superset_test(sep_base_test):
    """Every legal AW/W ordering delivers the write, at every transfer size."""

    async def run_scenario(self) -> None:
        cfg = SepAxiSupersetCfg(self.random_seed())
        self.logger.info("superset config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        sup = SepAxiSuperset(self)

        fails: list[str] = []
        for cell in cfg.cells:
            miss = await sup.run_cell(cell)
            if miss is None and cell.key in sup.covered:
                self.logger.info(
                    "CHK-ORDER PASS: %s %dB write landed (%s)",
                    cell.order, SIZE_BYTES[cell.size], cell.profile.summary())
            elif miss is not None:
                fails.append(miss)
                self.logger.error("CHK-ORDER FAIL: %s", miss)

        report = sup.coverage_report(cfg)
        if fails:
            raise AssertionError(
                f"CHK-ORDER FAIL: {len(fails)} cell(s) lost or corrupted the "
                f"write under a legal channel ordering; coverage {report}"
            )

        # A run that covered nothing must not look like a pass.
        assert sup.covered, (
            f"CHK-ORDER FAIL: no cell produced a data compare ({report}); "
            "the sweep asked the DUT nothing"
        )
        self.logger.info("CHK-ORDER PASS: %d cell(s) verified", len(sup.covered))
        self.logger.info("CHK-COVERAGE: %s", report)
        self.logger.info(
            "CHK-RANDCFG PASS: %d/%d cells from seed %d",
            len(sup.covered), cfg.n_cells(), cfg.seed)
