# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario body for the DRBG lane-adapter concurrent-channel leaves.

No `@pyuvm.test()` here: the runner discovers tests by scanning the
module it was given, so a registered class in a shared module would run under
every leaf name. Each leaf module subclasses this and registers itself.

One (lane x ordering) per leaf so a wedge cannot contaminate a later cell.
Two fabric leaves give two independent verdicts -- one per DUT lane on the
one ordering the fabric can present.

CHK-CONCURRENT-CAL: a lone write and a lone read measure when AW, W and AR
actually reach the adapter port through the crossbar and axi_to_axi_lite.
Placement is from those measurements, not guessed.

CHK-CONCURRENT-STIM: the ordering the ADAPTER PORT presented must be the
named ordering. A different overlap, or a cell that missed its overlap, is
reported unreachable and does not count as this leaf.

CHK-CONCURRENT-LAND: both accesses retire and the write lands. The check is
a bounded timeout plus a data compare, so a hang that `ASSERT_KNOWN` would
miss still fails the leaf.
"""

from __future__ import annotations

from sep_base_test import sep_base_test
from seq_lib.sep_axi_concurrent_rw_seq import (
    LANE_ADDRS,
    SepAxiConcurrentRw,
    SepAxiConcurrentRwCfg,
)


class sep_drbg_axil_concurrent_base(sep_base_test):
    """AR overlapping a write on one DRBG AXI-Lite-64 lane adapter."""

    SWEEP_BUS = "s_axi"
    LANE: str = ""
    ORDER: str = ""

    async def open_lane_path(self) -> None:
        """Make the lane's registers reachable from SWEEP_BUS.

        The CPU-LSU splice reaches them already; a gated bus opens its gate
        here.
        """

    async def run_scenario(self) -> None:
        cfg = SepAxiConcurrentRwCfg(
            self.random_seed(), lane=self.LANE, order=self.ORDER, bus=self.SWEEP_BUS
        )
        self.logger.info("concurrent-channel cell: %s", cfg.summary())
        await self.bring_up_no_cpu()
        await self.open_lane_path()
        walk = SepAxiConcurrentRw(self, bus=self.SWEEP_BUS)

        # Reachability probe, not a check: a closed gate would fail the cell on
        # its prime write and read as an arbitration defect.
        wr_addr, _rd_addr = LANE_ADDRS[cfg.lane]
        resp = await walk.probe_read(wr_addr)
        assert resp == 0, (
            f"CHK-CONCURRENT-CAL FAIL: {cfg.lane} 0x{wr_addr:08x} answered "
            f"resp={resp} to a plain read from {self.SWEEP_BUS}; the lane is "
            f"not reachable, so the cell would measure the gate, not the adapter"
        )

        miss = await walk.run_cell(cfg)
        if miss is not None:
            self.logger.error("CHK-CONCURRENT-LAND FAIL: %s", miss)
            raise AssertionError(f"CHK-CONCURRENT-LAND FAIL: {miss}")

        assert walk.unreachable is None, (
            f"CHK-CONCURRENT-STIM FAIL: {cfg.lane} {cfg.order} never reached "
            f"its AW/W/AR overlap at the adapter port ({walk.unreachable}), so "
            f"the arbitration contract was not exercised there"
        )
        self.logger.info(
            "CHK-CONCURRENT-STIM PASS: %s %s presented at the adapter port (%s)",
            cfg.lane,
            cfg.order,
            walk.observation,
        )
        self.logger.info(
            "CHK-CONCURRENT-LAND PASS: %s %s retired both accesses and landed "
            "the write with AR overlapping for %d cycle(s)",
            cfg.lane,
            cfg.order,
            walk.covered,
        )
