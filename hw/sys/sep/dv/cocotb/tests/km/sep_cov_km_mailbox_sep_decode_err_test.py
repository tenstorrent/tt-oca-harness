# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Code-coverage stimulus for the km_mailbox_sep_reg decode-error path.

no_cpu / +skip_fuse_sense. No KM ROM: the SEP mailbox window is the only
inbound AXI-Lite slave on key_manager, so this reaches the SEP-side regblock
directly.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_cov_km_seq import KM_MBOX_BASE
from seq_lib.sep_km_mailbox_seq import KM_MBOX_READ_DATA, KM_MBOX_WRITE_DATA

# One word past KM_MAILBOX_SEP_SIZE (0x1C) and still inside the regblock's
# five-bit address decode.
_PAST_BLOCK_OFFSET = 0x1C


@pyuvm.test()
class sep_cov_km_mailbox_sep_decode_err_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Three accesses the SEP-side mailbox regblock decodes as errors: a read of
    the write-only SEP_WRITE_DATA, a write of the read-only SEP_READ_DATA, and
    an access one word past the block. km_mailbox.sv intercepts writes at
    offset 0x0 and reads at offset 0x8 only, so the opposite direction of each
    reaches the regblock and takes its ``decoded_err`` leg.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        probes = (
            ("read write-only SEP_WRITE_DATA", SepAxiOp.READ, KM_MBOX_WRITE_DATA, 0),
            ("write read-only SEP_READ_DATA", SepAxiOp.WRITE, KM_MBOX_READ_DATA, 0xA5A5_5A5A),
            ("read past the block", SepAxiOp.READ, _PAST_BLOCK_OFFSET, 0),
            ("write past the block", SepAxiOp.WRITE, _PAST_BLOCK_OFFSET, 0x1234_5678),
        )
        for label, op, offset, wdata in probes:
            seq = SepAxiAccessSeq(
                f"km_mbox_decode_{offset:02x}_{op.name.lower()}",
                op=op,
                addr=KM_MBOX_BASE + offset,
                wdata=wdata,
                size=2,
                allow_error=True,
            )
            mon = getattr(self.env, "axi_monitor", None)
            if mon is not None:
                mon.arm_expected_decerr(1)
            await self.start_seq(seq)
            self.logger.info(
                "STEP %s at offset 0x%02x: resp=%d rdata=0x%08x",
                label,
                offset,
                seq.resp_code,
                seq.rdata,
            )

        self.logger.info("STEP km_mailbox_sep decode-error stimulus complete")
