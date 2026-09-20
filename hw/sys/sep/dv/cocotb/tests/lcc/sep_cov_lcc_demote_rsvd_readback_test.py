# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reserved storage of the lifecycle DEMOTE registers.

``DEMOTE_1`` and ``DEMOTE_2`` are 64-bit registers with ``demote`` at bit 0,
``lock`` at bit 1 and ``rsvd`` over bits 63:2
(``regs/blocks/sep_lifecycle_ctrl/sep_lifecycle_ctrl.rdl``). The demote walks
in the suite write bit 0 only, so ``sep_lifecycle_ctrl_reg`` holds the other
62 bits of each register at reset for every run.

The stimulus writes all-ones and all-zeros across the reserved bits of both
registers, reading each back. The patterns keep ``lock`` clear: setting it
closes the register to every later write, so a literal all-ones write would
make the second half of its own walk a no-op. ``demote`` is kept clear too,
because it moves the lifecycle feature vector and this leaf is not a
lifecycle test.

``+skip_fuse_sense``, LC TEST_DEV: the register is plain storage in the LCC
and the sensed image does not gate it.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_LIFECYCLE_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

DEMOTE_1 = sym("SEP_LIFECYCLE_CTRL_DEMOTE_1_REG_ADDR")
DEMOTE_2 = sym("SEP_LIFECYCLE_CTRL_DEMOTE_2_REG_ADDR")

DEMOTE_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "demote")
LOCK_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "lock")
RSVD_MASK = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "rsvd")

# All-ones over the reserved bits, with demote and lock left clear.
PATTERNS = (RSVD_MASK, 0, 0x5555_5555_5555_5555 & RSVD_MASK, 0xAAAA_AAAA_AAAA_AAAA & RSVD_MASK, 0)


@pyuvm.test()
class sep_cov_lcc_demote_rsvd_readback_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def _walk(self, addr: int, name: str) -> None:
        for pattern in PATTERNS:
            assert not pattern & (DEMOTE_BIT | LOCK_BIT), (
                f"{name} pattern 0x{pattern:016x} touches demote or lock; the lock "
                "bit would close the register to the rest of this walk"
            )
            wr = SepAxiAccessSeq(
                f"{name}_wr_0x{pattern:016x}",
                op=SepAxiOp.WRITE,
                addr=addr,
                wdata=pattern,
                length=8,
                size=3,
            )
            await self.start_seq(wr)
            rd = SepAxiAccessSeq(
                f"{name}_rd",
                op=SepAxiOp.READ,
                addr=addr,
                length=8,
                size=3,
            )
            await self.start_seq(rd)
            self.logger.info("[cov] %s wrote 0x%016x, read 0x%016x", name, pattern, rd.rdata)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        await self._walk(DEMOTE_1, "DEMOTE_1")
        await self._walk(DEMOTE_2, "DEMOTE_2")
