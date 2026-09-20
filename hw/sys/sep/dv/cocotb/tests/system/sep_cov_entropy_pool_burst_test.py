# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Multi-beat INCR bursts over the entropy-pool aperture (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_entropy_pool_seq import POOL_BASE, POOL_STATUS
from seq_lib.sep_esrc_bringup_seq import (
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
    SepEsrcFifoDrainSeq,
)

AXI_BURST_INCR = 1
BEAT_BYTES = 8
# Two beats reach the status and irq-cause offsets; three reach the pop
# offset at +0x10 as the last beat of the burst.
BURST_BEATS = (2, 3)
# Pool occupancy lives in the low bits of STATUS; the poll is flow control so
# the three-beat burst does not pop an empty pool.
POOL_LEVEL_MASK = 0x3F
_FILL_POLL_ROUNDS = 400
_FILL_POLL_CYCLES = 200
_DRAIN_GAP_CYCLES = 40


@pyuvm.test()
class sep_cov_entropy_pool_burst_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    The SEP-level entropy-FIFO target sits behind ``u_axi_to_axi_lite``, whose
    burst splitter and atop filter only see single-beat traffic from the rest
    of the suite. These are legal INCR reads of two and three 64-bit beats
    over the pool aperture, so the splitter divides one AXI burst into
    successive AXI-Lite reads. No read value is inspected.

    The fill poll before the three-beat burst is flow control: the last beat
    of that burst lands on the pop offset, which needs a non-empty pool.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _drain_fifo_loop(self) -> None:
        """Keep the ESRC output FIFO drained so the seed path does not stall.

        ``sep_base_test.start_fifo_drain`` feeds the DRBG scoreboard, which a
        stimulus-only test does not build, so the drain runs here instead.
        """
        while not self._drain_stop:
            await self.start_seq(SepEsrcFifoDrainSeq("esrc_fifo_drain"))
            await ClockCycles(cocotb.top.clk_i, _DRAIN_GAP_CYCLES)

    async def _status_level(self) -> int:
        seq = SepAxiAccessSeq(
            "pool_cov_status", op=SepAxiOp.READ, addr=POOL_STATUS, length=BEAT_BYTES, size=None
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError("entropy-pool STATUS read not OKAY")
        return seq.rdata & POOL_LEVEL_MASK

    async def _burst_read(self, beats: int) -> None:
        seq = SepAxiAccessSeq(
            f"pool_cov_burst{beats}",
            op=SepAxiOp.READ,
            addr=POOL_BASE,
            length=beats * BEAT_BYTES,
            size=None,
            burst=AXI_BURST_INCR,
        )
        await self.start_seq(seq)
        self.logger.info("cov stimulus: drove a %d-beat INCR read over the pool aperture", beats)

    async def _wait_pool_filled(self) -> int:
        for _ in range(_FILL_POLL_ROUNDS):
            level = await self._status_level()
            if level > 0:
                return level
            await ClockCycles(cocotb.top.clk_i, _FILL_POLL_CYCLES)
        raise AssertionError(
            "stimulus precondition: the entropy pool never filled, so the pop beat "
            "of the three-beat burst cannot be driven"
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        noise = self.start_esrc_noise_driver()
        drain = None
        try:
            await self._burst_read(BURST_BEATS[0])
            await self.start_seq(SepEsrcConfigSeq("esrc_config"))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                raise AssertionError("stimulus precondition: ESRC never produced a seed")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))
            self._drain_stop = False
            drain = cocotb.start_soon(self._drain_fifo_loop())
            level = await self._wait_pool_filled()
            self.logger.info("cov stimulus: pool level %d before the pop burst", level)
            await self._burst_read(BURST_BEATS[1])
        finally:
            self._drain_stop = True
            if drain is not None:
                drain.kill()
            noise.kill()
