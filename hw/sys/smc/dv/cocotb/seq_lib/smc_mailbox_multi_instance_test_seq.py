# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P1 coverage-gap round 2: mailbox multi-instance sweep.

Round 1 `smc_mailbox_inbound_test` only touches inbound mailbox 0. RTL
exposes **32 outbound + 32 inbound** mailbox instances at:

  * SMC_MAILBOX_OUTBOUND_MAILBOX_N (smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)
  * SMC_MAILBOX_INBOUND_MAILBOX_N  (smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + N * 0x1000)

This test reads the STATUS register (offset +0x010 for outbound,
+0x010 for inbound at +0x800 sub-offset) of every instance to prove
each mailbox pair's decode is alive. Bounded reads — clock-gate is
enabled upfront but individual mailboxes may DECERR without traffic.
"""

from __future__ import annotations

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Same generated header the sibling `smc_mailbox_irq_test_seq.py:28-31` reads.
_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox_smc_wrap.h"
)
# Idle STATUS of an untouched mailbox, per field from the generated header --
# the same constant the sibling `smc_mailbox_irq_test_seq.py:67` compares
# against and passes with. EMPTY is "1: Data is not available to read"
# (axil_mailbox.rdl), and FULL / *_LEVEL_ABOVE_THRESH are 0.
MAILBOX_STATUS_IDLE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")

_CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
_MAILBOX_CG_EN = 1 << 1

_OUTBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR")
_INBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR")
_MAILBOX_STRIDE = 0x1000
_STATUS_OFFSET = 0x010

_MAILBOX_COUNT = 32
# IRQEN is the ONE mailbox register in this block that a CSR test can genuinely
# prove: `axi_lite_mailbox.sv:465-469` implements it as real 3-bit storage
# (`irqen_d[2:0] = slv_req_i.w.data[2:0]`), so a write/read-back has teeth.
#
# The rest of the mailbox map does NOT, and is deliberately not swept:
#   * `IRQS` is write-1-to-clear only (:452-461) -- software can never set a bit
#   * `IRQP` is `assign irqp_q = irqs_q & irqen_q`, read-only derived
#   * `CTRL` is `sw = w` self-clearing, so a readback is always 0
#   * `WIRQT`/`RIRQT` clamp to MailboxDepth-1 and `smc_pkg::MAILBOX_DEPTH = 2`,
#     so every written value >= 2 reads back as 1 -- one bit of information
#   * `STATUS`/`READ_DATA`/`ERROR_FLAGS` are declared `sw = r; hw = r` in the
#     RDL, which is issue #1238: unwritable from either side, so no
#     generated-model CSR test should be credited with covering them.
_IRQEN_OFFSET = 0x038
_IRQEN_MASK = 0x7


class smc_mailbox_multi_instance_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        # Every outbound/inbound mailbox STATUS must return an OKAY response:
        # csr_read routes through the scoreboard which asserts item.resp_ok, so a
        # missing/mis-decoded mailbox instance (DECERR or bus hang) fails the test.
        # All 64 instances are real and reachable in the OSS bench (return OKAY).
        # Do NOT use csr_read_bounded here — it tolerates a dead mailbox and makes
        # the sweep vacuous.
        # Every one of these 64 reads carries `expected=`. Without it the
        # scoreboard books `resp_ok` only and no value is compared. Issue #1238
        # -- STATUS is declared `sw = r; hw = r` in the RDL, so a generated
        # model cannot express it -- is about what the RDL can express, not
        # about whether the idle value is derivable: it is derivable from the
        # generated field mask, and the sibling
        # `smc_mailbox_irq_test_seq.py:67,150` compares against exactly this
        # constant.
        for i in range(_MAILBOX_COUNT):
            addr = _OUTBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_OUT_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
        for i in range(_MAILBOX_COUNT):
            addr = _INBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_IN_{i}_STATUS", addr, expected=MAILBOX_STATUS_IDLE)
        # IRQEN write/read-back/restore on mailbox 0 of each direction. Unlike
        # the STATUS sweep above -- which passes no `expected=` and therefore
        # books NO scoreboard value check, proving decode only -- these compares
        # are enforced by the scoreboard and fail on a wrong word.
        for label, base in (
            ("MBOX_OUT_0", _OUTBOUND_MAILBOX_BASE),
            ("MBOX_IN_0", _INBOUND_MAILBOX_BASE),
        ):
            addr = base + _IRQEN_OFFSET
            await self.csr_read(f"{label}_IRQEN_RESET", addr, expected=0)
            await self.csr_write(f"{label}_IRQEN_WR", addr, _IRQEN_MASK)
            await self.csr_read(f"{label}_IRQEN_RB", addr, expected=_IRQEN_MASK)
            await self.csr_write(f"{label}_IRQEN_RESTORE", addr, 0)
            await self.csr_read(f"{label}_IRQEN_RESTORE_RB", addr, expected=0)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # `self.accesses` is bumped by this sequence's own csr_* calls, so
        # asserting it against a literal only restates the loops above and
        # cannot fail on anything the DUT did ([NO-ALWAYS-PASS-CHECKER]).
        # `assert_all_reachable` cross-checks the same count against the
        # scoreboard instead.
        self.assert_all_reachable(3 + 2 * _MAILBOX_COUNT + 10, "MAILBOX_MULTI_INSTANCE")
