# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI channel-ordering sweep: every legal AW/W ordering must land, everywhere.

no_cpu / +skip_fuse_sense. AXI write address and write data are independent
channels with no ordering requirement between them (IHI 0022 A3.3), so
AW-first, W-first and same-cycle are all legal stimulus and every one must
leave the written value in the addressed register.

Each block behind the crossbar terminates AXI at its own register adapter, so
the ordering contract has to hold at every one of them, not at one scratch
word. The sweep drives all three orderings at every register the generated
export establishes as write-safe storage, and crosses ordering with the 1/2/4
byte sizes on the scratch words, where a narrow write has no side effect.

CHK-ORDER-LAND: the write lands. The cell primes with the complement first, so
a write that never lands reads back as the prime rather than looking plausible.
This is the class of defect a response check cannot see: an adapter that
latches a pending-write flag on AW accept and reads that flag in the same cycle
the W arrives answers OKAY while dropping the data.

CHK-ORDER-DISPLACE: the NEXT write in the block lands on the register it
addresses. A pending flag left set by the ordering makes the following W
handshake commit to the wrong target, which the land check cannot see because
it reads the register that was written, not the neighbour that was corrupted.

CHK-ORDER-XSIZE: all nine (ordering x size) cells produced a data compare, so
the ordering axis is proven crossed with the lane axis and not only at the bus
width.

CHK-COVERAGE: the cell tally is logged, including every cell that could not run
and why. A dropped cell is named rather than absorbed, so partial coverage
never reads as a full sweep.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_axi_order_sweep_seq import (
    SIZE_BYTES,
    SepAxiOrderSweep,
    SepAxiOrderSweepCfg,
)


@pyuvm.test()
class sep_axi_order_sweep_test(sep_base_test):
    """Every legal AW/W ordering delivers the write, at every register."""

    async def run_scenario(self) -> None:
        cfg = SepAxiOrderSweepCfg(self.random_seed())
        self.logger.info("order sweep config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        sweep = SepAxiOrderSweep(self)

        fails: list[str] = []
        for cell in cfg.cells:
            miss = await sweep.run_cell(cell)
            if miss is not None:
                fails.append(miss)
                self.logger.error("CHK-ORDER-LAND FAIL: %s", miss)
            elif cell.key in sweep.dropped:
                self.logger.info(
                    "CHK-ORDER-LAND DROP: %s %dB %s.%s not driven (%s)",
                    cell.order, SIZE_BYTES[cell.size], cell.info.block,
                    cell.info.name, sweep.dropped[cell.key])

        report = sweep.coverage_report(cfg)
        if fails:
            raise AssertionError(
                f"CHK-ORDER-LAND FAIL: {len(fails)} cell(s) lost, corrupted or "
                f"displaced the write under a legal channel ordering; "
                f"coverage {report}"
            )

        compares = sum(sweep.covered.values())
        assert compares == cfg.n_cells(), (
            f"CHK-ORDER-LAND FAIL: {compares} of {cfg.n_cells()} cells "
            f"produced a data compare ({report}); every legal ordering must be "
            "exercised at every swept register, not just the ones that "
            "happened to run"
        )
        self.logger.info(
            "CHK-ORDER-LAND PASS: %d cell(s) verified across %d block(s)",
            compares, len(sweep.blocks_hit))

        missing_cross = cfg.cross_cells() - set(sweep.cross_covered)
        assert not missing_cross, (
            f"CHK-ORDER-XSIZE FAIL: {sorted(missing_cross)} produced no data "
            f"compare ({report}); the ordering axis is not crossed with size"
        )
        self.logger.info(
            "CHK-ORDER-XSIZE PASS: %d/%d (ordering x size) cell(s) verified",
            len(sweep.cross_covered), len(cfg.cross_cells()))

        # The displacement check needs a second register in the block to write.
        # Without one the cell proves only the land contract, so the count is
        # reported rather than assumed equal to the cell count.
        assert sweep.witnessed > 0, (
            f"CHK-ORDER-DISPLACE FAIL: no cell ran a follow-on write, so the "
            f"displaced-write contract was never tested ({report})"
        )
        self.logger.info(
            "CHK-ORDER-DISPLACE PASS: %d follow-on write(s) landed on the "
            "register they addressed", sweep.witnessed)

        self.logger.info("CHK-COVERAGE: %s", report)
        self.logger.info(
            "CHK-RANDCFG PASS: %d/%d cells from seed %d",
            compares, cfg.n_cells(), cfg.seed)
