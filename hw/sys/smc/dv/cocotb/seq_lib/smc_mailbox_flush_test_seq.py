# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CTRL.wflush empties the write FIFO it claims to flush.

CTRL cannot be a readback test at all. `axil_mailbox.rdl` makes both
its fields `sw = w; hw = r`: they are flush strobes, not storage, so a
write/read-back pair would compare against whatever the register file returns
for a write-only address and prove nothing. What is testable is the effect, and
STATUS reports it: `write_level_above_thresh` @0x10 bit 2 is the write FIFO's
level measured against WIRQT.

So the property is a transition, and it needs the level to be *up* first:

1. WIRQT := 0 and read it back, so the threshold under which "above" is
   measured is known rather than assumed, and the port is proven writable.
2. STATUS must read `write_level_above_thresh == 0` with the FIFO empty.
3. Push one word into WRITE_DATA. STATUS must now read it as 1. **This is the
   positive control.** Without it, step 4 is satisfied by a STATUS that reads
   zero for every reason including a dead one ([NEGATIVE-NEEDS-POSITIVE-
   CONTROL]).
4. Write CTRL.wflush. STATUS must return to 0.

Every address and field mask comes from the generated maps -- `smc_addr.h` for
the addresses, `axil_mailbox.h` for the bit masks
([ADDRESS-FROM-AUTHORITATIVE-MAP]).

Nothing in this bench drains the outbound write FIFO on its own: its far side
is the paired inbound port's read side, which is read only by an explicit
INBOUND_READ_DATA access. So a level that falls between steps 3 and 4 fell
because of the flush.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)

OUTBOUND_WRITE_DATA = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR")
OUTBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR")
OUTBOUND_WIRQT = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_WIRQT_BASE_ADDR")
OUTBOUND_CTRL = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_CTRL_BASE_ADDR")

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)

WRITE_LEVEL_ABOVE_THRESH = _field_mask(
    _AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm"
)
WIRQT_MASK = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__WIRQT__WIRQT_bm")
CTRL_WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")

# One word is enough: with WIRQT at 0 any occupancy is "above threshold", and a
# single entry keeps the FIFO far from full so a failure cannot be blamed on
# backpressure.
FLUSH_PAYLOAD = 0x0BAD_F10E_0BAD_F10E


class smc_mailbox_flush_test_seq(SmcCsrSeq):
    """CTRL.wflush, measured through the STATUS level bit it moves."""

    async def _level(self, name: str) -> int:
        status = await self.csr_read(name, OUTBOUND_STATUS, length=8)
        return status & WRITE_LEVEL_ABOVE_THRESH

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)

        # Threshold 0, read back: the meaning of "above threshold" below is
        # then a measured fact, and the read-back is this port's liveness.
        await self.csr_write("MBOX_WIRQT_ZERO", OUTBOUND_WIRQT, 0, length=8)
        wirqt = await self.csr_read("MBOX_WIRQT_RB", OUTBOUND_WIRQT, length=8)
        assert (wirqt & WIRQT_MASK) == 0, (
            f"WIRQT read back 0x{wirqt:016x} after writing 0; the threshold the "
            "level bit is measured against is not what this testcase set"
        )

        empty_before = await self._level("MBOX_STATUS_BEFORE")
        assert empty_before == 0, (
            f"STATUS.write_level_above_thresh is already set (0x{empty_before:x}) "
            "with nothing pushed. The FIFO is not empty at the start, so a fall "
            "after the flush would not be attributable to this testcase's push."
        )

        await self.csr_write("MBOX_PUSH", OUTBOUND_WRITE_DATA, FLUSH_PAYLOAD, length=8)
        pushed = await self._level("MBOX_STATUS_PUSHED")
        assert pushed == WRITE_LEVEL_ABOVE_THRESH, (
            "CHK-MBOX-FLUSH-ARM: STATUS.write_level_above_thresh stayed clear "
            f"after pushing one word with WIRQT=0 (status level bit=0x{pushed:x}). "
            "Nothing was queued, so the flush below would have nothing to flush "
            "and its result would be vacuous."
        )
        cocotb.log.info(
            "CHK-MBOX-FLUSH-ARM: one word pushed with WIRQT=0 raised "
            "STATUS.write_level_above_thresh, so the flush has something to act on"
        )

        await self.csr_write("MBOX_WFLUSH", OUTBOUND_CTRL, CTRL_WFLUSH, length=8)
        flushed = await self._level("MBOX_STATUS_FLUSHED")
        assert flushed == 0, (
            "CHK-MBOX-FLUSH: CTRL.wflush did not empty the write FIFO -- "
            f"STATUS.write_level_above_thresh is still 0x{flushed:x} with WIRQT=0. "
            "The strobe is write-only, so this bit is the only evidence it did "
            "anything."
        )
        cocotb.log.info(
            "CHK-MBOX-FLUSH: CTRL.wflush cleared STATUS.write_level_above_thresh, "
            "which the push had raised"
        )

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
