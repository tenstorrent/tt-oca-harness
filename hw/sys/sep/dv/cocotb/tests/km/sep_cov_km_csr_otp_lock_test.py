# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the OTP_READ_LOCK and OTP_CHANGE_STATUS legs.

no_cpu, real fuse sense (no +skip_fuse_sense), +km_rom_hex=km_rom_cov_csr.parhex
-- the same image as sep_cov_km_csr_otp_shadow_walk_test, which reads the block
first and writes the locks afterwards. Both registers are on the KM CPU bus.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done


@pyuvm.test()
class sep_cov_km_csr_otp_lock_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    One write of all nine field bits to OTP_READ_LOCK drives every W1S leg,
    and one write of all nine to OTP_CHANGE_STATUS drives every W1C leg. Both
    are warm-reset fields, so the image writes them after boot.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        # Real fuse sense (no +skip_fuse_sense): the base class requires a golden
        # image before sense-done, so stage LC_PROD and let KM read real OTP.
        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self)
        self.logger.info("STEP OTP lock write stimulus complete: km_sram_word0_o=0x%08x", word)
