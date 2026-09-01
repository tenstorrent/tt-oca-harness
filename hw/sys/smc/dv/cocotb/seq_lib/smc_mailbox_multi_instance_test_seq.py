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

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
_MAILBOX_CG_EN = 1 << 1

_OUTBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR")
_INBOUND_MAILBOX_BASE = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR")
_MAILBOX_STRIDE = 0x1000
_STATUS_OFFSET = 0x010

_MAILBOX_COUNT = 32


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
        for i in range(_MAILBOX_COUNT):
            addr = _OUTBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_OUT_{i}_STATUS", addr)
        for i in range(_MAILBOX_COUNT):
            addr = _INBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + _STATUS_OFFSET
            await self.csr_read(f"MBOX_IN_{i}_STATUS", addr)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # Expected: 2 CG accesses + 32 out + 32 in + 1 restore = 67
        assert self.accesses == 3 + 2 * _MAILBOX_COUNT, "mailbox multi-instance sweep mismatch"
