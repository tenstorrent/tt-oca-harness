# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for three recoverable KM CPU fault IRQ legs.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_fault.parhex. Every fault
source is on the KM CPU bus, so they run from a KM ROM image.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done

# The image reports before the fetch fault, which parks the KM CPU. The settle
# window lets that last fault land.
_SETTLE_CYCLES = 2_000


@pyuvm.test()
class sep_cov_km_csr_fault_irq_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Three faults in sequence: a store into the KM ROM window for
    ``rom_write_err``, an access to an address matching no km_axi_lite_xbar
    rule for ``axi_decerr``, and a committed fetch from a peripheral address
    for ``exec_violation``. IRQ_STATUS is W1C-cleared between the first two.
    The ``.next`` leg of each of these fields is tied off in km_csr.sv, so the
    HW-set leg is the only live input.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self, settle_cycles=_SETTLE_CYCLES)
        self.logger.info("STEP KM fault IRQ stimulus complete: km_sram_word0_o=0x%08x", word)
