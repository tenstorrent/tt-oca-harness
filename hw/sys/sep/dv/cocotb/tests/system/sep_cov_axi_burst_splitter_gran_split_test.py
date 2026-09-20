# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Multi-beat bursts into an AXI-Lite-backed CSR block, to drive the burst splitter."""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import (
    BURST_INCR,
    SIZE_4B,
    SepCovAxiStim,
    incr_bytes,
    pattern,
)

# The entropy-pool FIFO CSR block. `axi_burst_splitter_gran` sits inside every
# `axi_to_axi_lite`, so any AXI-Lite-backed CSR block reaches it; this one is
# chosen because its allocated span is exactly six 4-byte registers, which
# makes a 16-beat burst from its base run off the end of the block without
# having to place the tail by hand.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv:
#   OCH_SEP_TOP_ENTROPY_POOL_BASE_ADDR = 0x10950000
#   OCH_SEP_TOP_ENTROPY_POOL_SIZE      = 0x18
EPOOL_BASE = 0x1095_0000
EPOOL_SIZE = 0x18

# Fully inside the block: six 4-byte beats.
IN_RANGE_BEATS = EPOOL_SIZE // (1 << SIZE_4B)
IN_RANGE_BYTES = incr_bytes(IN_RANGE_BEATS, SIZE_4B)

# Past the end of the block: the leading beats decode, the tail beats land in
# the hole above it and come back as an error. Aggregating an error from part
# of a split burst is the only way `b_err_q` is set.
OVERRUN_BEATS = 16
OVERRUN_BYTES = incr_bytes(OVERRUN_BEATS, SIZE_4B)


@pyuvm.test()
class sep_cov_axi_burst_splitter_gran_split_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    A 4-byte-beat INCR burst into an AXI-Lite-backed CSR block must be cut
    into single-beat Lite transfers by `axi_burst_splitter_gran`. The present
    suite drives AxLEN=0 into every CSR block, so the splitter's granularity
    counters and its per-beat response aggregation stay at reset.

    Three shapes: a read and a write that fit inside the block, and a burst
    that starts inside it and runs off the end, so some split beats decode and
    the rest do not. Per-beat and aggregate responses are logged, not graded:
    this leaf drives the splitter, it does not state what the decode owes.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        await stim.burst(
            "epool_read_in_range",
            op=SepAxiOp.READ,
            addr=EPOOL_BASE,
            length=IN_RANGE_BYTES,
            size=SIZE_4B,
            burst=BURST_INCR,
        )
        await stim.settle()
        await stim.burst(
            "epool_write_in_range",
            op=SepAxiOp.WRITE,
            addr=EPOOL_BASE,
            length=IN_RANGE_BYTES,
            size=SIZE_4B,
            burst=BURST_INCR,
            wdata=pattern(rng, IN_RANGE_BYTES),
        )
        await stim.settle()
        await stim.burst(
            "epool_read_overrun",
            op=SepAxiOp.READ,
            addr=EPOOL_BASE,
            length=OVERRUN_BYTES,
            size=SIZE_4B,
            burst=BURST_INCR,
        )
        await stim.settle()
        await stim.burst(
            "epool_write_overrun",
            op=SepAxiOp.WRITE,
            addr=EPOOL_BASE,
            length=OVERRUN_BYTES,
            size=SIZE_4B,
            burst=BURST_INCR,
            wdata=pattern(rng, OVERRUN_BYTES),
        )
        await stim.settle()

        stim.record(
            "COV-AXI-BURST-SPLITTER",
            f"{IN_RANGE_BEATS}-beat in-range and {OVERRUN_BEATS}-beat "
            "overrunning INCR reads and writes at AxSIZE=2 into an "
            "AXI-Lite-backed CSR block",
        )
