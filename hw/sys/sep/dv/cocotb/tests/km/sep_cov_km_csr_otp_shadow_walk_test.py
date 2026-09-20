# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the km_csr_reg OTP shadow readback mux.

no_cpu, real fuse sense (no +skip_fuse_sense) so the shadows carry data,
+km_rom_hex=km_rom_cov_csr.parhex. KMCSR is behind km_axi_lite_xbar, whose
single slave port is the SEP mailbox, so the walk runs from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done


@pyuvm.test()
class sep_cov_km_csr_otp_shadow_walk_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image reads every word of the KMCSR block, which drives one readback
    mux leg per OTP shadow register and per VUART, TB and lock register.
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
        self.logger.info("STEP KMCSR readback walk complete: km_sram_word0_o=0x%08x", word)
