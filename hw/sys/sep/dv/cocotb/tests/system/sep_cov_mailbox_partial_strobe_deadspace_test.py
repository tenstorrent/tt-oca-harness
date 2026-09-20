# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox partial-strobe writes and in-bank dead space (coverage stimulus).

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

OUTBOUND_BASE = sym("AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR")
WRITE_DATA = AXIL_MAILBOX_OUTBOUND_0.offset("WRITE_DATA")
CTRL = AXIL_MAILBOX_OUTBOUND_0.offset("CTRL")
CTRL_WFLUSH = AXIL_MAILBOX_OUTBOUND_0.field_mask("CTRL", "wflush")
# Offsets inside bank 0 that decode to no register: above CTRL (0x48) and
# below the inbound aperture at 0x800.
DEAD_OFFSETS = (0x50, 0x80, 0x400, 0x7F8)


@pyuvm.test()
class sep_cov_mailbox_partial_strobe_deadspace_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    ``WRITE_DATA`` is a 64-bit register. A 4-byte write at its base strobes
    only ``w.strb[3:0]`` and a 4-byte write four bytes up strobes only
    ``w.strb[7:4]``; the mailbox zeroes the unstrobed bytes. The suite
    otherwise pushes full 8-byte beats, so those strobe patterns and the low
    address bits never move.

    The dead offsets inside bank 0 decode to no register and answer with an
    error response, which moves ``r.resp[0]`` and ``b.resp[0]``.
    ``allow_error`` tells the agent that a non-OKAY response is the documented
    outcome of an unmapped offset; no response code is scored.

    Payload words come from ``SepSeededRng``, so the stimulus is a pure
    function of the run seed.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _half_write(self, addr: int, value: int) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_half_wr_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=value,
            length=4,
            size=2,
            allow_unverified_write_resp=True,
        )
        await self.start_seq(seq)

    async def _dead_access(self, addr: int, *, op: SepAxiOp, wdata: int = 0) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_dead_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            allow_error=True,
        )
        await self.start_seq(seq)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())

        for _ in range(2):
            await self._half_write(OUTBOUND_BASE + WRITE_DATA, rng.getrandbits(32))
            await self._half_write(OUTBOUND_BASE + WRITE_DATA + 4, rng.getrandbits(32))
        flush = SepAxiAccessSeq(
            "mbox_cov_wflush",
            op=SepAxiOp.WRITE,
            addr=OUTBOUND_BASE + CTRL,
            wdata=CTRL_WFLUSH,
            length=4,
            size=2,
        )
        await self.start_seq(flush)
        self.logger.info("cov stimulus: drove both WRITE_DATA half-word strobes")

        for offset in DEAD_OFFSETS:
            addr = OUTBOUND_BASE + offset
            await self._dead_access(addr, op=SepAxiOp.READ)
            await self._dead_access(addr, op=SepAxiOp.WRITE, wdata=rng.getrandbits(32))
        self.logger.info("cov stimulus: drove %d in-bank dead offsets r+w", len(DEAD_OFFSETS))
