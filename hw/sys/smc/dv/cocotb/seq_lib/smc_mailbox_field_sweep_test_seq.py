# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-mailbox field sweep, both directions.

Reads every readable field of mailboxes 0-3 on the outbound port and on the
inbound port, to prove each mailbox's field decode is alive. A read that
mis-decodes answers DECERR or hangs, and `csr_read` routes through the
scoreboard's `item.resp_ok` assert, so it fails. `csr_read_bounded` is
deliberately not used: it would tolerate a dead field and make the sweep
vacuous.

The offset list is the whole coverage claim, so it is checked against the RDL
rather than trusted. `axil_mailbox.rdl:214-224` declares ten registers per
port; this list holds the eight that are readable:

  WRITE_DATA  +0x000  omitted -- a read pops the paired port's FIFO, which is
                      state this sweep must not disturb
  READ_DATA   +0x008  omitted for the same reason
  STATUS      +0x010
  ERROR_FLAGS +0x018
  WIRQT       +0x020
  RIRQT       +0x028
  IRQS        +0x030  (write-1-to-clear)
  IRQEN       +0x038
  IRQP        +0x040  `irqs_q & irqen_q`, read-only derived
  CTRL        +0x048  omitted -- `sw = w` flush strobes, nothing to read.
                      Covered by its effect in `smc_mailbox_flush_test`

IRQP and the inbound port were added after a measured pass over the whole
regression's AXI transactions found that no enrolled testcase drove IRQP on
either port, or IRQS / WIRQT / RIRQT / IRQP on the inbound one. The miss was
structural: an offset list that stops short, on a port that was never swept,
stays silent as the block grows. That is why the list above is now written
against the RDL with a reason for each omission.
"""

from __future__ import annotations

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)  # base_config offset 0x18
_MAILBOX_CG_EN = 1 << 1
_MAILBOX_STRIDE = 0x1000

_PORTS = [
    ("OUT", smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR")),
    ("IN", smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR")),
]

_FIELD_OFFSETS = [
    ("STATUS", 0x010),
    ("ERROR_FLAGS", 0x018),
    ("WIRQT", 0x020),
    ("RIRQT", 0x028),
    ("IRQS", 0x030),
    ("IRQEN", 0x038),
    ("IRQP", 0x040),
]

_MAILBOX_COUNT = 4


class smc_mailbox_field_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        for port, base in _PORTS:
            for i in range(_MAILBOX_COUNT):
                for name, off in _FIELD_OFFSETS:
                    addr = base + i * _MAILBOX_STRIDE + off
                    await self.csr_read(f"MBOX_{port}_{i}_{name}", addr)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        # 2 CG + ports*N*fields + 1 restore
        expected = 3 + len(_PORTS) * _MAILBOX_COUNT * len(_FIELD_OFFSETS)
        assert self.accesses == expected, (
            f"mailbox field sweep mismatch: got {self.accesses}, expected {expected}"
        )
