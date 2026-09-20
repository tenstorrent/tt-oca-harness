# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MIN_ENTROPY_H.H sweep over the recommended-threshold LUT (coverage stimulus).

no_cpu / +skip_fuse_sense. No entropy flow is needed: the LUT is combinational
on one register field.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_esrc_seq import (
    ESRC_MIN_ENTROPY_H,
    ESRC_RECOMMENDED_THRESHOLDS,
    MIN_ENTROPY_H_VALUES,
    SepCovEsrc,
)


@pyuvm.test()
class sep_cov_esrc_thresh_lut_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``entropy_source_rec_thresh_lut`` is a 256-arm unique case whose only input
    is ``min_entropy_h_i[7:0]``, assigned from ``MIN_ENTROPY_H.H`` at
    ``hw/ip/entropy_source/rtl/entropy_source.sv:828`` and instanced at
    ``:830-833``. Writing every value of that field selects every arm; the
    RECOMMENDED_THRESHOLDS read after each write moves the ``rct_limit_o`` /
    ``apt_limit_o`` outputs onto the register bus. The read value is not
    inspected.

    ``MIN_ENTROPY_H.H`` is ``swwel``-gated by ``FIPS_LOCK.LOCK``
    (``entropy_source.sv:784``), so this test never writes ``FIPS_LOCK``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        esrc = SepCovEsrc(self)
        for h in range(MIN_ENTROPY_H_VALUES):
            await esrc.wr(ESRC_MIN_ENTROPY_H, h)
            await esrc.rd(ESRC_RECOMMENDED_THRESHOLDS)
        self.logger.info(
            "cov stimulus: drove %d MIN_ENTROPY_H values through the LUT",
            MIN_ENTROPY_H_VALUES,
        )
