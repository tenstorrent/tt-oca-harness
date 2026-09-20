# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the picorv32_wrapper ROM lockout.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_lockout.parhex. SRAM
execution needs SRAM_EXEC_MODE and the SRAM write lock, both on the KM CPU
bus, so the sequence runs from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done

# The image posts its first word from SRAM execution and its second after the
# ROM load, so the run reads word0 again once it has settled.
_SETTLE_CYCLES = 2_000


@pyuvm.test()
class sep_cov_km_rom_lockout_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image enables SRAM_EXEC_MODE, copies a stub into an SRAM region,
    write-locks that region and jumps to it. The first committed fetch from
    SRAM latches ``rom_lockout_q``; a ROM load afterwards drives
    ``rom_access_violation_o`` and the matching IRQ_STATUS HW-set leg.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self, settle_cycles=_SETTLE_CYCLES)
        self.logger.info("STEP ROM lockout stimulus complete: km_sram_word0_o=0x%08x", word)
