# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario body for the DRBG lane-adapter concurrent-channel leaves.

No `@pyuvm.test()` here: the runner discovers tests by scanning the
module it was given, so a registered class in a shared module would run under
every leaf name. Each leaf module subclasses this and registers itself.

One (lane x ordering) per leaf so a wedge cannot contaminate a later cell.
Two fabric leaves give two independent verdicts -- one per DUT lane on the
one ordering the fabric can present.

CHK-CONCURRENT-CAL: the writable mask of INTR_ENABLE, measured by an
all-ones write and readback, equals the union of its fields in the generated
register header. A lone write and a lone read measure when AW, W and AR
actually reach the adapter port through the crossbar and axi_to_axi_lite.
Placement is from those measurements, not guessed.

CHK-CONCURRENT-STIM: the ordering the ADAPTER PORT presented must be the
named ordering. A different overlap, or a cell that missed its overlap, is
reported unreachable and does not count as this leaf.

CHK-CONCURRENT-ARB: at the adapter port, AR handshakes only after both AW
and W have handshaken. The adapter accepts a read only when neither write
half is pending.

CHK-CONCURRENT-LAND: both accesses retire and the write lands. The check is
a bounded timeout plus a data compare, so a hang that `ASSERT_KNOWN` would
miss still fails the leaf.

FCOV: the owner window of the leaf (docs/SEP_FCOV.adoc) opens after the mask
probe, the calibration and the prime, one clock before the overlapping pair,
and closes after CHK-CONCURRENT-LAND passes, or first on any FAIL. The
sampler holds the legal ``x_drbg_lane_arb`` cell of the lane as seen at the AR
handshake and samples it only when the leaf sets the lane bit of
``crypto_bus_pass`` after STIM, ARB and LAND pass. The illegal cell samples at
the handshake.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.sep_fcov_gate import (
    CRYPTO_BUS_PASS_LANE_ARB,
    close_graded_window,
    open_graded_window,
    set_crypto_bus_pass,
)
from sep_base_test import sep_base_test
from seq_lib.sep_axi_concurrent_rw_seq import (
    LANE_ADDRS,
    SepAxiConcurrentRw,
    SepAxiConcurrentRwCfg,
)

# Bit of ``u_sep_fcov.crypto_bus_pass`` that names the legal
# ``x_drbg_lane_arb`` cell of each lane (cov/sv/sep_fcov.sv).
LANE_ARB_PASS_BIT: dict[str, int] = {
    "csrng": CRYPTO_BUS_PASS_LANE_ARB,
    "edn": CRYPTO_BUS_PASS_LANE_ARB + 1,
}

# Clock edges between the pass label and the window close, so the sampler sees
# the label rise while the owner window is still open.
LABEL_SETTLE_EDGES = 2


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

        owner = type(self).__name__
        shot = False

        async def open_window() -> None:
            nonlocal shot
            shot = True
            set_crypto_bus_pass(0, log=self.logger)
            open_graded_window(owner, log=self.logger)
            await RisingEdge(cocotb.top.clk_i)

        def fail(msg: str) -> None:
            close_graded_window(log=self.logger)
            self.logger.error("%s", msg)
            raise AssertionError(msg)

        try:
            miss = await walk.run_cell(cfg, on_shot=open_window)
            if miss is not None:
                fail(f"CHK-CONCURRENT-{'LAND' if shot else 'CAL'} FAIL: {miss}")

            if walk.unreachable is not None:
                fail(
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
            hs = walk.hs
            if not all(hs[ch] is not None for ch in ("aw", "w", "ar")):
                fail(
                    f"CHK-CONCURRENT-ARB FAIL: {cfg.lane} {cfg.order} retired without "
                    f"all three handshakes recorded at the adapter port (AW={hs['aw']} "
                    f"W={hs['w']} AR={hs['ar']})"
                )
            if not hs["ar"] > max(hs["aw"], hs["w"]):
                fail(
                    f"CHK-CONCURRENT-ARB FAIL: {cfg.lane} {cfg.order} AR handshook at "
                    f"cycle {hs['ar']} while a write half was pending (AW={hs['aw']} "
                    f"W={hs['w']}); the adapter accepts a read only when neither write "
                    f"half is pending"
                )
            self.logger.info(
                "CHK-CONCURRENT-ARB PASS: %s %s held AR until both write halves "
                "handshook (AW=%d W=%d AR=%d)",
                cfg.lane,
                cfg.order,
                hs["aw"],
                hs["w"],
                hs["ar"],
            )
            self.logger.info(
                "CHK-CONCURRENT-LAND PASS: %s %s retired both accesses and landed "
                "the write with AR overlapping for %d cycle(s)",
                cfg.lane,
                cfg.order,
                walk.covered,
            )
            set_crypto_bus_pass(1 << LANE_ARB_PASS_BIT[cfg.lane], log=self.logger)
            for _ in range(LABEL_SETTLE_EDGES):
                await RisingEdge(cocotb.top.clk_i)
        finally:
            close_graded_window(log=self.logger)
