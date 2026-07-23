# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 3: per-mailbox field sweep.

Round 1/2 only touched STATUS. Each outbound mailbox exposes 6+ CSR
fields at fixed offsets. This test reads STATUS + ERROR_FLAGS +
WIRQT + RIRQT + IRQEN + IRQS from outbound mailboxes 0-3 to prove
every mailbox's field decode is alive.

Register offsets within a mailbox (offset from base + N * 0x1000):
* STATUS       +0x010
* ERROR_FLAGS  +0x018
* WIRQT        +0x020
* RIRQT        +0x028
* IRQEN        +0x038
* IRQS         +0x030  (write-1-to-clear)
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
_MAILBOX_CG_EN = 1 << 1
_OUTBOUND_MAILBOX_BASE = 0xC001_8000
_MAILBOX_STRIDE = 0x1000

_FIELD_OFFSETS = [
    ("STATUS",       0x010),
    ("ERROR_FLAGS",  0x018),
    ("WIRQT",        0x020),
    ("RIRQT",        0x028),
    ("IRQS",         0x030),
    ("IRQEN",        0x038),
]

_MAILBOX_COUNT = 4


class smc_mailbox_field_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL,
                             cg | _MAILBOX_CG_EN)
        # Every mailbox field read must return OKAY: csr_read routes through the
        # scoreboard's item.resp_ok assert, so a mis-decoded field (DECERR/hang)
        # fails the test. These outbound mailbox fields are real and reachable in
        # the OSS bench (all return OKAY). csr_read_bounded is intentionally NOT
        # used here — it would tolerate a dead field and make the sweep vacuous.
        for i in range(_MAILBOX_COUNT):
            for name, off in _FIELD_OFFSETS:
                addr = _OUTBOUND_MAILBOX_BASE + i * _MAILBOX_STRIDE + off
                await self.csr_read(f"MBOX_OUT_{i}_{name}", addr)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE",
                             _CLOCK_GATE_CONTROL, cg)
        # 2 CG + N*fields + 1 restore
        expected = 3 + _MAILBOX_COUNT * len(_FIELD_OFFSETS)
        assert self.accesses == expected, (
            f"mailbox field sweep mismatch: got {self.accesses}, "
            f"expected {expected}"
        )
