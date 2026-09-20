# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Non-zero downsample rate (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_cov_esrc_seq import ESRC_CTRL, SepCovEsrc, bring_up_esrc_generators

# A short and a full-scale reload value for the 10-bit counter, both built
# from the generated field metadata so MODULE_ENABLE (reset 1) stays set.
_RATES = (0x00F, 0x3FF)
_RUN_CYCLES = 8_000
_DRAIN_ROUNDS = 4


@pyuvm.test()
class sep_cov_esrc_downsample_rate_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``downsample_count`` at
    ``hw/ip/entropy_source/rtl/entropy_source.sv:613-622`` reloads from
    ``CTRL.DOWNSAMPLE_RATE`` and decrements on every gated stream beat. The
    decrement arm is live only while the field is non-zero, which the suite
    otherwise leaves at its zero reset.

    ``CTRL.DOWNSAMPLE_RATE`` is ``swwel``-gated by ``FIPS_LOCK.LOCK``
    (``entropy_source.sv:794``), so this test never writes ``FIPS_LOCK``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            for rate in _RATES:
                await esrc.wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", DOWNSAMPLE_RATE=rate))
                popped = 0
                for _ in range(_DRAIN_ROUNDS):
                    await ClockCycles(cocotb.top.clk_i, _RUN_CYCLES)
                    popped += await esrc.drain_entropy_fifo()
                self.logger.info(
                    "cov stimulus: ran at DOWNSAMPLE_RATE=0x%03x, popped %d words", rate, popped
                )
            await esrc.wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", DOWNSAMPLE_RATE=0))
        finally:
            noise.kill()
