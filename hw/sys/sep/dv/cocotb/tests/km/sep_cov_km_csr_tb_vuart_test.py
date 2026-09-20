# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the KMCSR VUART, TB and lock registers.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_tbvuart.parhex. These
registers are on the KM CPU bus, so the writes run from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done


@pyuvm.test()
class sep_cov_km_csr_tb_vuart_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image writes VUART_TX, the TB_* result and command registers,
    SRAM_EXEC_MODE and IRQ_ENTRY_LOCK, then stores into a write-locked SRAM
    region to drive the SRAM_WRITE_LOCK_VIOLATION HW-set leg.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self)
        self.logger.info("STEP KMCSR TB/VUART stimulus complete: km_sram_word0_o=0x%08x", word)
