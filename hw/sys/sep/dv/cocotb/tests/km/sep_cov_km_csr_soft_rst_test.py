# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the KMCSR SOFT_RST_CODE path.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_softrst.parhex.
SOFT_RST_CODE is on the KM CPU bus, so the write runs from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done

# The soft reset restarts the image, and the second boot posts its own word.
_SETTLE_CYCLES = 20_000


@pyuvm.test()
class sep_cov_km_csr_soft_rst_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image posts its progress word, then writes the SOFT_RST_CODE magic.
    The match drives ``soft_rst_o``, which the reset conditioner returns as a
    warm reset, so ``soft_rst_q`` clears and the register self-clears. KM SRAM
    survives the warm reset, so the second boot takes the halt leg and the
    reset does not repeat.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self, settle_cycles=_SETTLE_CYCLES)
        self.logger.info("STEP soft-reset stimulus complete: km_sram_word0_o=0x%08x", word)
