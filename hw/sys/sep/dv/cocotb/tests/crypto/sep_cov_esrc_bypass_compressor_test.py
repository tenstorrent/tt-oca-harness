# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-compressor bypass FIFO-push path (coverage stimulus).

no_cpu / +skip_fuse_sense / +esrc_noise_force.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_cov_esrc_seq import ESRC_CTRL, SepCovEsrc, bring_up_esrc_generators

# CTRL built from the generated field metadata so MODULE_ENABLE, which resets
# to 1, stays set: a hand-built literal would disable the whole entropy source.
CTRL_BYPASS = ENTROPY_SOURCE.value("CTRL", BYPASS_ENTROPY_COMPRESSOR=1)
CTRL_NO_BYPASS = ENTROPY_SOURCE.value("CTRL", BYPASS_ENTROPY_COMPRESSOR=0)

_RUN_CYCLES = 8_000
_DRAIN_ROUNDS = 8


@pyuvm.test()
class sep_cov_esrc_bypass_compressor_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    The FIFO-push state machine at
    ``hw/ip/entropy_source/rtl/entropy_source.sv:639-689`` takes its
    ``ST_FIFO_PUSH`` arm only while ``CTRL.BYPASS_ENTROPY_COMPRESSOR`` is set:
    the uncompressed stream is pushed four bytes at a time under
    ``fifo_push_count``. With the bypass clear the same states push one
    whitened word. Draining ``FIFO_RDATA`` between runs keeps the FIFO from
    stalling the push.

    ``CTRL.BYPASS_ENTROPY_COMPRESSOR`` is ``swwel``-gated by ``FIPS_LOCK.LOCK``
    (``entropy_source.sv:788``), so this test never writes ``FIPS_LOCK``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        noise = await bring_up_esrc_generators(self)
        try:
            esrc = SepCovEsrc(self)
            await esrc.wr(ESRC_CTRL, CTRL_BYPASS)
            popped = 0
            for _ in range(_DRAIN_ROUNDS):
                await ClockCycles(cocotb.top.clk_i, _RUN_CYCLES)
                popped += await esrc.drain_entropy_fifo()
            await esrc.wr(ESRC_CTRL, CTRL_NO_BYPASS)
            await ClockCycles(cocotb.top.clk_i, _RUN_CYCLES)
            popped += await esrc.drain_entropy_fifo()
            self.logger.info("cov stimulus: popped %d FIFO words across both push modes", popped)
        finally:
            noise.kill()
