# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the km_drbg_sampler prefetch consume path.

no_cpu / +skip_fuse_sense / +esrc_noise_force /
+km_rom_hex=km_rom_cov_drbg_prefetch.parhex. The entropy stack is brought up
without the DRBG scoreboard: this test grades nothing, it only needs entropy
that moves. The sampler registers are on the KM CPU bus, so the reads run from
a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_post_cfg, km_cov_release, wait_km_cov_done
from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)

# The image only needs a word to unblock on; it programs CFG itself.
_GO_WORD = 0x0000_0001


@pyuvm.test()
class sep_cov_km_drbg_prefetch_read_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    With the internal DRBG leg selected and entropy flowing, the image sets
    CFG.prefetch, polls STATUS.prefetched, then reads PREFETCH_DATA and DATA.
    That drives the PREFETCH_DATA readback leg and the ``prefetched_valid``
    consume path.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        noise = self.start_esrc_noise_driver()
        try:
            cfg = SepEntropyCfg()
            await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
            await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
            if not await self.wait_seed_ready():
                await self.report_entropy_stall()
                raise AssertionError("ESRC never produced a seed, so the prefetch has no source")
            await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))
            self.logger.info("STEP entropy stack up on the internal DRBG leg")

            await km_cov_release(self)
            await km_cov_post_cfg(self, _GO_WORD)
            word = await wait_km_cov_done(self)
        finally:
            noise.kill()
        self.logger.info("STEP DRBG prefetch stimulus complete: km_sram_word0_o=0x%08x", word)
