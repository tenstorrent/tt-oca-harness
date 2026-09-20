# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the SEP-side mailbox sticky overflow/underflow bits.

no_cpu / +skip_fuse_sense. No KM ROM: the KM stays in software reset, which is
what keeps the inbound FIFO undrained and the outbound FIFO empty. RANDCFG:
the number of pushes past the FIFO depth comes from the run seed.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_cov_km_seq import KM_MBOX_BASE
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_DEPTH,
    KM_MBOX_IRQ_STATUS,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
)

_W1C_ALL = 0xFFFF_FFFF


@pyuvm.test()
class sep_cov_km_mailbox_sep_sticky_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Overfills the inbound FIFO and reads the empty outbound FIFO, which drives
    the ``hwset`` legs of SEP_STATUS.inbound_overflow / outbound_underflow and
    the matching SEP_IRQ_STATUS fields, then writes all ones to both registers
    to drive their W1C legs. The ``.next`` legs of these fields are tied off in
    km_mailbox.sv, so ``hwset`` is the only live input.

    SEP_IRQ_STATUS.flushed_by_km is not driven here: the flush comes from the
    KM side and needs a KM ROM image.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        extra = rng.randrange(1, 5)
        pushes = KM_MBOX_DEPTH + extra
        self.logger.info(
            "km mailbox sticky: seed=%d depth=%d pushes=%d",
            self.random_seed(),
            KM_MBOX_DEPTH,
            pushes,
        )

        await self.bring_up_no_cpu()

        async def _read(label: str, offset: int, *, allow_error: bool = False) -> int:
            seq = SepAxiAccessSeq(
                f"km_sticky_rd_{offset:02x}",
                op=SepAxiOp.READ,
                addr=KM_MBOX_BASE + offset,
                size=2,
                allow_error=allow_error,
            )
            await self.start_seq(seq)
            self.logger.info("STEP read %s: resp=%d data=0x%08x", label, seq.resp_code, seq.rdata)
            return seq.rdata

        await _read("SEP_STATUS before the overfill", KM_MBOX_STATUS)

        for i in range(pushes):
            # The response to the overflowing push is selected by
            # SEP_CTRL.inbound_overflow_resp, so it is tolerated rather than
            # required; the sticky bit is the stimulus target.
            seq = SepAxiAccessSeq(
                f"km_sticky_push_{i}",
                op=SepAxiOp.WRITE,
                addr=KM_MBOX_BASE + KM_MBOX_WRITE_DATA,
                wdata=0xC0DE_0000 | i,
                size=2,
                allow_unverified_write_resp=True,
            )
            await self.start_seq(seq)
        self.logger.info("STEP pushed %d words into a %d-entry inbound FIFO", pushes, KM_MBOX_DEPTH)

        await _read("SEP_READ_DATA with the outbound FIFO empty", KM_MBOX_READ_DATA,
                    allow_error=True)
        await _read("SEP_STATUS after the overfill and the empty read", KM_MBOX_STATUS)
        await _read("SEP_IRQ_STATUS after the overfill and the empty read", KM_MBOX_IRQ_STATUS)

        for label, offset in (
            ("SEP_STATUS", KM_MBOX_STATUS),
            ("SEP_IRQ_STATUS", KM_MBOX_IRQ_STATUS),
        ):
            seq = SepAxiAccessSeq(
                f"km_sticky_w1c_{offset:02x}",
                op=SepAxiOp.WRITE,
                addr=KM_MBOX_BASE + offset,
                wdata=_W1C_ALL,
                size=2,
                allow_unverified_write_resp=True,
            )
            await self.start_seq(seq)
            self.logger.info("STEP W1C %s", label)

        await _read("SEP_STATUS after W1C", KM_MBOX_STATUS)
        await _read("SEP_IRQ_STATUS after W1C", KM_MBOX_IRQ_STATUS)

        self.logger.info("STEP km_mailbox_sep sticky overflow/underflow stimulus complete")
