# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared ring-oscillator select sweep (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from seq_lib.sep_cov_esrc_seq import (
    ESRC_RING_OSC_CTRL,
    SAMPLE_CLK_SELECT_ALL,
    SepCovEsrc,
    bring_up_esrc_generators,
)

_SETTLE_CYCLES = 2_000
# Every lane on the shared ring oscillator, every lane on the core sample
# clock, and an alternating pattern so the select mux resolves both ways
# within one vector.
_SELECT_PATTERNS = (SAMPLE_CLK_SELECT_ALL, 0x000, 0x555)


@pyuvm.test()
class sep_cov_esrc_shared_ro_select_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``hw/ip/entropy_source/rtl/entropy_sampler_clocks.sv:75`` picks each lane's
    clock between ``u_shared_ro`` (instanced at ``:65-72``) and ``sample_clk_i``
    from ``sample_clk_select_i[i]``, which carries
    ``RING_OSC_CTRL.SAMPLE_CLK_SELECT``. Running the generators at each pattern
    toggles the shared oscillator and both mux legs.

    That field is ``swwel``-gated by ``FIPS_LOCK.LOCK``
    (``entropy_source.sv:799``), so this test never writes ``FIPS_LOCK``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            for pattern in _SELECT_PATTERNS:
                await esrc.wr(ESRC_RING_OSC_CTRL, pattern)
                await ClockCycles(cocotb.top.clk_i, _SETTLE_CYCLES)
                await esrc.drain_entropy_fifo()
                self.logger.info(
                    "cov stimulus: ran the generators at SAMPLE_CLK_SELECT=0x%03x", pattern
                )
        finally:
            noise.kill()
