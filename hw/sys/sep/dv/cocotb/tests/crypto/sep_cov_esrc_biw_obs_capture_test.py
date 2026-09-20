# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bit-in-word observe capture (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_cov_esrc_seq import (
    ESRC_BIW_OBS_CTRL,
    ESRC_BIW_OBS_RDATA,
    ESRC_BIW_OBS_STATUS,
    SepCovEsrc,
    bring_up_esrc_generators,
)

_CAPTURE_CYCLES = 8_000
_DRAIN_ROUNDS = 8
BIW_OBS_ENABLE = ENTROPY_SOURCE.value("BIW_OBS_CTRL", RAW_ENABLE=1)
BIW_OBS_DISABLE = ENTROPY_SOURCE.value("BIW_OBS_CTRL", RAW_ENABLE=0)


@pyuvm.test()
class sep_cov_esrc_biw_obs_capture_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``BIW_OBS_CTRL.RAW_ENABLE`` opens the bit-in-word observe tap into
    ``u_biw_obs_fifo``. Running the generators fills it and the
    ``BIW_OBS_RDATA`` reads pop it. The ``BIW_OBS_STATUS.LEVEL`` poll is flow
    control -- it bounds the pops so the FIFO cannot underflow -- and the popped
    values are not inspected.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            await esrc.wr(ESRC_BIW_OBS_CTRL, BIW_OBS_ENABLE)
            total = 0
            for _ in range(_DRAIN_ROUNDS):
                await ClockCycles(cocotb.top.clk_i, _CAPTURE_CYCLES)
                total += await esrc.drain_obs_fifo(ESRC_BIW_OBS_STATUS, ESRC_BIW_OBS_RDATA)
            await esrc.wr(ESRC_BIW_OBS_CTRL, BIW_OBS_DISABLE)
            self.logger.info("cov stimulus: popped %d BIW observe words", total)
        finally:
            noise.kill()
