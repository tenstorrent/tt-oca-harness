# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the replicated km_kpv_reg CTRL slots.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_kpv_walk.parhex. RANDCFG:
the first slot and the walk stride come from the run seed. KPV CTRL is behind
km_axi_lite_xbar, whose single slave port is the SEP mailbox, so the walk runs
from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import (
    cfg_fold,
    km_cov_post_cfg,
    km_cov_release,
    wait_km_cov_done,
)

_N_SLOTS = 64


@pyuvm.test()
class sep_cov_km_kpv_ctrl_slot_walk_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image walks all 64 CTRL slots with an odd stride. Even slots take the
    sealed leg, so their erase retires through the HW-set inputs; odd slots
    take the unsealed leg, so their erase frees through the HW-clear inputs.
    Between them the SW-write-1-set legs of lock_write, lock_use, erase and
    seal are driven on every replicated instance.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        start_slot = rng.randrange(_N_SLOTS)
        stride = rng.randrange(0, 16) | 1
        cfg_word = (start_slot & 0x3F) | ((stride & 0xF) << 8)
        self.logger.info(
            "km kpv walk: seed=%d start_slot=%d stride=%d cfg=0x%08x fold=0x%02x",
            self.random_seed(),
            start_slot,
            stride,
            cfg_word,
            cfg_fold(cfg_word),
        )

        await self.bring_up_no_cpu()
        await km_cov_release(self)
        await km_cov_post_cfg(self, cfg_word)

        word = await wait_km_cov_done(self)
        self.logger.info("STEP KPV CTRL slot walk complete: km_sram_word0_o=0x%08x", word)
