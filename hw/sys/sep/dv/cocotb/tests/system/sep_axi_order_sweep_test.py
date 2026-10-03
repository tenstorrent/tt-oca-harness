# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI channel-ordering sweep: every legal AW/W ordering at the s_axi ingress lands.

no_cpu / +skip_fuse_sense. AXI write address and write data are independent
channels with no ordering requirement between them (IHI 0022 A3.3), so all
three orderings are legal stimulus and each must leave the written value in
the addressed register. The orderings are presented at the s_axi fabric
ingress, and the contract is end to end: each one must land at every
write-safe register of every swept block, not only at one scratch word. The
crossbar in front of the block adapters can re-serialize a write (the CSRNG
path delivers W one cycle after AW whatever the master presents), so this
test does not claim that each adapter sees all three orderings. W-first and
same-cycle orderings at an adapter port are covered for the DRBG lane adapter
module by sep_drbg_axil_adapter_port_arbitration_test.

The sweep configures all three orderings at every register the export
establishes as write-safe storage, and crosses them with the 1/2/4-byte sizes
on the scratch words, where a narrow write has no side effect.

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
    S_AXI_CELL_FLOOR,
    SIZE_BYTES,
    WRITE_ORDERS,
    SepAxiOrderSweep,
    SepAxiOrderSweepCfg,
)


@pyuvm.test()
class sep_axi_order_sweep_test(sep_base_test):
    """Every legal AW/W ordering delivers the write, at every register."""

    SWEEP_BUS = "s_axi"
    CELL_FLOOR = S_AXI_CELL_FLOOR

    async def open_sweep_path(self, cfg: SepAxiOrderSweepCfg) -> None:
        """Make the swept registers reachable from SWEEP_BUS.

        The CPU-LSU splice reaches them already; a bus that is gated opens its
        gate here.
        """

    async def run_scenario(self) -> None:
        cfg = SepAxiOrderSweepCfg(self.random_seed(), bus=self.SWEEP_BUS)
        self.logger.info("order sweep config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        await self.open_sweep_path(cfg)
        sweep = SepAxiOrderSweep(self, bus=self.SWEEP_BUS)

        fails: list[str] = []
        for cell in cfg.cells:
            miss = await sweep.run_cell(cell)
            if miss is not None:
                fails.append(miss)
                self.logger.error("CHK-ORDER-LAND FAIL: %s", miss)
            elif cell.key in sweep.dropped:
                self.logger.info(
                    "CHK-ORDER-LAND DROP: %s %dB %s.%s not driven (%s)",
                    cell.order,
                    SIZE_BYTES[cell.size],
                    cell.info.block,
                    cell.info.name,
                    sweep.dropped[cell.key],
                )

        report = sweep.coverage_report(cfg)
        if fails:
            raise AssertionError(
                f"CHK-ORDER-LAND FAIL: {len(fails)} cell(s) lost, corrupted or "
                f"displaced the write under a legal channel ordering; "
                f"coverage {report}"
            )

        compares = sum(sweep.covered.values())
        assert compares >= self.CELL_FLOOR, (
            f"CHK-COVERAGE FAIL: the walk ran {compares} cells, below the "
            f"floor of {self.CELL_FLOOR}; a shrinking walk must not pass "
            f"silently ({cfg.summary()})"
        )
        assert compares == cfg.n_cells(), (
            f"CHK-ORDER-LAND FAIL: {compares} of {cfg.n_cells()} cells "
            f"produced a data compare ({report}); every legal ordering must be "
            "exercised at every swept register, not just the ones that "
            "happened to run"
        )
        self.logger.info(
            "CHK-ORDER-LAND PASS: %d cell(s) verified across %d block(s)",
            compares,
            len(sweep.blocks_hit),
        )

        missing_cross = cfg.cross_cells() - set(sweep.cross_covered)
        assert not missing_cross, (
            f"CHK-ORDER-XSIZE FAIL: {sorted(missing_cross)} produced no data "
            f"compare ({report}); the ordering axis is not crossed with size"
        )
        self.logger.info(
            "CHK-ORDER-XSIZE PASS: %d/%d (ordering x size) cell(s) verified",
            len(sweep.cross_covered),
            len(cfg.cross_cells()),
        )

        # The displacement check needs a second register in the block to
        # write; a cell in a single-register block proves the land contract
        # alone. Every cell that CAN carry the check must have completed it,
        # so the count is compared against the configured total rather than
        # merely being non-zero.
        assert sweep.witnessed == cfg.n_witnessed(), (
            f"CHK-ORDER-DISPLACE FAIL: {sweep.witnessed} of "
            f"{cfg.n_witnessed()} cell(s) completed a follow-on write; the "
            f"displaced-write contract was not tested where it could be "
            f"({report})"
        )
        self.logger.info(
            "CHK-ORDER-DISPLACE PASS: %d follow-on write(s) landed on the register they addressed",
            sweep.witnessed,
        )

        # CHK-ORDER-STIM: the ordering each cell PRESENTED on the bus, read
        # off the AW/W valid assertions rather than taken from the profile
        # that was requested. run_cell fails a cell whose presentation does
        # not match, so reaching here means all three orderings were driven.
        want = {o for o, _a, _w in WRITE_ORDERS}
        assert set(sweep.stim_seen) == want, (
            f"CHK-ORDER-STIM FAIL: presented {sorted(sweep.stim_seen)}, expected {sorted(want)}"
        )
        self.logger.info(
            "CHK-ORDER-STIM PASS: presented %s; slave handshake %s",
            " ".join(f"{k}={v}" for k, v in sorted(sweep.stim_seen.items())),
            " ".join(f"{k}={v}" for k, v in sorted(sweep.hs_seen.items())),
        )

        self.logger.info(
            "CHK-COVERAGE PASS: %d cell(s) run, at or above the floor of %d",
            compares,
            self.CELL_FLOOR,
        )
        self.logger.info("CHK-COVERAGE: %s", report)
        self.logger.info(
            "CHK-RANDCFG PASS: %d/%d cells from seed %d", compares, cfg.n_cells(), cfg.seed
        )
