# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the KM-side mailbox decode and sticky legs.

no_cpu / +skip_fuse_sense / +km_rom_hex=km_rom_cov_mbox_km.parhex. The KM-side
mailbox window sits behind km_axi_lite_xbar, so it is reachable only from a KM
ROM image. The host posts nothing: the image needs its inbound FIFO empty for
the underflow read.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_km_seq import km_cov_release, wait_km_cov_done


@pyuvm.test()
class sep_cov_km_mailbox_km_decode_err_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    The image reads the write-only KM_WRITE_DATA and writes the read-only
    KM_READ_DATA, which take the regblock ``decoded_err`` leg; overfills the
    outbound FIFO; reads the empty inbound FIFO; then writes all ones to
    KM_STATUS and KM_IRQ_STATUS to drive their W1C legs.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await km_cov_release(self)
        word = await wait_km_cov_done(self)
        self.logger.info("STEP KM-side mailbox stimulus complete: km_sram_word0_o=0x%08x", word)
