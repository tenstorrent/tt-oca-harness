# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write-path burst shapes into the 64-to-32 crypto downsizers."""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import (
    BURST_FIXED,
    BURST_INCR,
    BURST_WRAP,
    SIZE_8B,
    SepCovAxiStim,
    incr_bytes,
    pattern,
)

# Same two downsizer targets as the read-shape leaf.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv.
TARGETS = (("otbn_dmem", 0x1090_8000), ("hmac", 0x1091_1000))

SPLIT_BEATS = 129  # conv_ratio=2 -> 257 master beats -> W_SPLIT_INCR_DOWNSIZE
SPLIT_BYTES = incr_bytes(SPLIT_BEATS)
WRAP_BEATS = 4
WRAP_BYTES = incr_bytes(WRAP_BEATS)
WRAP_OFFSET = 0x40
FIXED_BEATS = 4
FIXED_BYTES = incr_bytes(FIXED_BEATS)

# Cycles BREADY is held low after the split write, so the downsizer's B-forward
# path holds a response rather than retiring it in the cycle it arrives.
B_BACKPRESSURE_CYCLES = 8


@pyuvm.test()
class sep_cov_axi_dw_write_burst_shape_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Write burst shapes through the crypto `axi_dw_downsizer` instances: the
    over-255-beat INCR split with B backpressure, single-beat and multi-beat
    FIXED, and WRAP. Payload bytes come from `env/sep_seeded_rng.py`, so the
    beats are a pure function of the run seed and nothing is compared against
    them.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()
        drv = stim.timing_driver()

        for name, base in TARGETS:
            # BREADY held low for the split write only: the B-forward FIFO in
            # the downsizer is only occupied while a response waits.
            drv.set_timing(AxiTimingProfile(b_ready_delay=B_BACKPRESSURE_CYCLES))
            try:
                await stim.burst(
                    f"{name}_incr_split",
                    op=SepAxiOp.WRITE,
                    addr=base,
                    length=SPLIT_BYTES,
                    size=SIZE_8B,
                    burst=BURST_INCR,
                    wdata=pattern(rng, SPLIT_BYTES),
                )
            finally:
                drv.set_timing(AxiTimingProfile())
            await stim.settle()

            await stim.burst(
                f"{name}_fixed_1beat",
                op=SepAxiOp.WRITE,
                addr=base,
                length=1 << SIZE_8B,
                size=SIZE_8B,
                burst=BURST_FIXED,
                wdata=pattern(rng, 1 << SIZE_8B),
            )
            await stim.settle()
            await stim.burst(
                f"{name}_fixed_4beat",
                op=SepAxiOp.WRITE,
                addr=base,
                length=FIXED_BYTES,
                size=SIZE_8B,
                burst=BURST_FIXED,
                wdata=pattern(rng, FIXED_BYTES),
            )
            await stim.settle()
            await stim.burst(
                f"{name}_wrap_4beat",
                op=SepAxiOp.WRITE,
                addr=base + WRAP_OFFSET,
                length=WRAP_BYTES,
                size=SIZE_8B,
                burst=BURST_WRAP,
                wdata=pattern(rng, WRAP_BYTES),
            )
            await stim.settle()

        stim.record(
            "COV-AXI-DW-WRITE-SHAPE",
            "INCR split under B backpressure, FIXED single, FIXED multi-beat "
            f"and WRAP writes at AxSIZE=3 on {len(TARGETS)} crypto downsizer targets",
        )
