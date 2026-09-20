# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the km_drbg_sampler timeout path.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_drbg_timeout.parhex.
RANDCFG: the CFG.TIMEOUT value comes from the run seed. The sampler registers
are on the KM CPU bus, so the reads run from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_cov_km_seq import (
    cfg_fold,
    km_cov_post_cfg,
    km_cov_release,
    wait_km_cov_done,
)
from seq_lib.sep_esrc_bringup_seq import EXT_TRNG_SRC_SEL

# sep_ip_integration.sv ties ext_trng_axis_req_o to zero, so the ext_trng leg
# never asserts TVALID and every sampler read runs out to StTimeout.
_EXT_TRNG_LEG = 0x7


@pyuvm.test()
class sep_cov_km_drbg_timeout_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The host selects the ext_trng leg, then posts the timeout value. The image
    programs CFG.TIMEOUT and reads DATA three times: each read counts out into
    the sampler's timeout state and advances ``count_bad``. A write of all
    ones to STATUS afterwards drives the W1C legs of ``timeout_err``,
    ``count_bad`` and ``count_good``.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        timeout = rng.randrange(8, 256)
        self.logger.info(
            "km drbg timeout: seed=%d CFG.TIMEOUT=%d fold=0x%02x",
            self.random_seed(),
            timeout,
            cfg_fold(timeout),
        )

        await self.bring_up_no_cpu()

        sel = SepAxiAccessSeq(
            "ext_trng_src_sel",
            op=SepAxiOp.WRITE,
            addr=EXT_TRNG_SRC_SEL,
            wdata=_EXT_TRNG_LEG,
            size=2,
        )
        await self.start_seq(sel)
        self.logger.info("STEP EXT_TRNG_SRC_SEL = 0x%x (ext_trng leg, never TVALID)", _EXT_TRNG_LEG)

        await km_cov_release(self)
        await km_cov_post_cfg(self, timeout)

        word = await wait_km_cov_done(self)
        self.logger.info("STEP DRBG sampler timeout stimulus complete: km_sram_word0_o=0x%08x", word)
