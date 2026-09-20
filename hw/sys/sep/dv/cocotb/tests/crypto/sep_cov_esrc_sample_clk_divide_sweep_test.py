# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-lane sample-clock divide sweep (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_cov_esrc_seq import (
    GENERATOR_SAMPLE_CLK,
    SAMPLE_CLK_DIVIDE_MAX,
    SepCovEsrc,
    bring_up_esrc_generators,
)

# Cycles the generators run at each divide setting, so the selected tap of the
# ripple divider reaches the sampler.
_SETTLE_CYCLES = 2_000
# Arms 0..5 are the named taps of the unique case at
# hw/ip/entropy_source/rtl/entropy_sampler_clocks.sv:86-93; one value above
# them selects the `default` arm.
_NAMED_ARMS = 6


@pyuvm.test()
class sep_cov_esrc_sample_clk_divide_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``entropy_sampler_clocks.sv:84-94`` selects one ripple-divider tap per lane
    with a unique case on ``sample_clk_divide_i[i]``. Every lane takes its
    divide from ``GENERATOR_<n>_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE``. This
    walks all twelve lanes through the named arms and one value that lands on
    ``default``.

    That field is ``swwel``-gated by ``FIPS_LOCK.LOCK``
    (``entropy_source.sv:803-814``), so this test never writes ``FIPS_LOCK``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            for divide in list(range(_NAMED_ARMS)) + [SAMPLE_CLK_DIVIDE_MAX]:
                for addr in GENERATOR_SAMPLE_CLK:
                    await esrc.wr(addr, divide)
                await ClockCycles(cocotb.top.clk_i, _SETTLE_CYCLES)
                await esrc.drain_entropy_fifo()
                self.logger.info(
                    "cov stimulus: ran %d lanes at SAMPLE_CLK_DIVIDE=%d",
                    len(GENERATOR_SAMPLE_CLK),
                    divide,
                )
        finally:
            noise.kill()
