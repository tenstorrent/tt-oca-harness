# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw noise-observe capture on every lane (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_cov_esrc_seq import (
    ESRC_NOISE_OBS_CTRL,
    ESRC_NOISE_OBS_RDATA,
    ESRC_NOISE_OBS_STATUS,
    NUM_LANES,
    SepCovEsrc,
    bring_up_esrc_generators,
    noise_obs_ctrl,
)

# The packer needs 32 sampled bits to complete one observe word
# (hw/ip/entropy_source/rtl/entropy_source.sv:536-541), and the raw sample
# rate is the divided ring-oscillator clock, so each lane runs for a long
# window before its FIFO is drained.
_CAPTURE_CYCLES = 8_000


@pyuvm.test()
class sep_cov_esrc_noise_obs_raw_capture_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``NOISE_OBS_CTRL.RAW_ENABLE`` opens the raw observe tap and
    ``NOISE_OBS_CTRL.LANE_SEL`` picks the lane. The shift/count packer at
    ``hw/ip/entropy_source/rtl/entropy_source.sv:536-541`` assembles 32 raw
    samples into one word and pushes it into ``u_noise_obs_fifo``; the
    ``NOISE_OBS_RDATA`` reads pop it. The ``NOISE_OBS_STATUS.LEVEL`` poll is
    flow control -- it says how many pops the FIFO can accept -- and the popped
    values are not inspected. The final ``FLUSH`` pulse drives the observe-FIFO
    flush at ``entropy_source.sv:573``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            for lane in range(NUM_LANES):
                await esrc.wr(ESRC_NOISE_OBS_CTRL, noise_obs_ctrl(raw_enable=1, lane=lane))
                await ClockCycles(cocotb.top.clk_i, _CAPTURE_CYCLES)
                popped = await esrc.drain_obs_fifo(ESRC_NOISE_OBS_STATUS, ESRC_NOISE_OBS_RDATA)
                self.logger.info("cov stimulus: lane %d popped %d observe words", lane, popped)
            await esrc.wr(ESRC_NOISE_OBS_CTRL, noise_obs_ctrl(raw_enable=1, flush=1))
            await esrc.wr(ESRC_NOISE_OBS_CTRL, noise_obs_ctrl())
        finally:
            noise.kill()
