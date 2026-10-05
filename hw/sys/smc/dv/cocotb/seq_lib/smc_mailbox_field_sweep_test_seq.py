# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-mailbox field sweep, both directions.

Reads every readable register of mailboxes 0-3 on the outbound port and on the
inbound port, to prove each mailbox's field decode is alive. A read that
mis-decodes answers DECERR or hangs, and `csr_read` routes through the
scoreboard's `item.resp_ok` assert, so it fails; `csr_read_bounded` would
tolerate a dead field and make the sweep vacuous.

**The swept set is derived from the generated register map, not listed here.**
`_swept_fields` enumerates every `SMC_MAILBOX_<port>_MAILBOX_0_*_REG_OFFSET`
symbol in `regs/gen/py/smc_reg.py` and removes the three that cannot be read,
each named with its reason:

  WRITE_DATA  a read pops the paired port's FIFO -- state this sweep must not
              disturb
  READ_DATA   the same
  CTRL        `sw = w` flush strobes, nothing to read. Covered by its effect in
              `smc_mailbox_flush_test`

A register can leave the sweep only by leaving the map, the excluded names are
asserted to exist so that renaming one fails instead of silently widening the
sweep, and a register added to the block joins the sweep.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

_CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_MAILBOX_CG_EN = 1 << 1
_MAILBOX_STRIDE = 0x1000
_MAILBOX_COUNT = 4

# Registers a read would disturb or that have nothing to read, with the reason.
_UNREADABLE = {
    "WRITE_DATA": "a read pops the paired port's FIFO",
    "READ_DATA": "a read pops the paired port's FIFO",
    "CTRL": "sw = w flush strobes; covered by smc_mailbox_flush_test",
}


def _swept_fields(port: str) -> list[tuple[str, int]]:
    """Every register of mailbox 0 on this port in the generated map, less the unreadable ones."""
    text = (_SMC_REG_PY / "smc_reg.py").read_text()
    pattern = rf"^SMC_MAILBOX_{port}_MAILBOX_0_([A-Z0-9_]+)_REG_OFFSET = (0x[0-9A-Fa-f]+)$"
    found = {name: int(off, 16) for name, off in re.findall(pattern, text, re.M)}
    if not found:
        raise AssertionError(
            f"no SMC_MAILBOX_{port}_MAILBOX_0_*_REG_OFFSET symbols in smc_reg.py; "
            "the generated map moved and this sweep would silently cover nothing"
        )
    missing = sorted(set(_UNREADABLE) - set(found))
    if missing:
        raise AssertionError(
            f"{port}: {missing} are excluded from the sweep but no longer exist in the "
            "generated map. Re-read the RDL: either they were renamed, in which case the "
            "sweep is now reading a register it must not, or they were removed, in which "
            "case the exclusion is stale."
        )
    # The exclusion count is pinned: adding an exclusion shrinks the sweep, so
    # it requires an edit here and a reason in _UNREADABLE.
    if len(_UNREADABLE) != 3:
        raise AssertionError(
            f"{len(_UNREADABLE)} registers are excluded from the sweep, not 3. Adding an "
            "exclusion removes a register from the only testcase that reads it, so it "
            "needs a stated reason in _UNREADABLE and this count updated deliberately."
        )
    return sorted((n, off) for n, off in found.items() if n not in _UNREADABLE)


_PORTS = [
    (
        "OUT",
        smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR"),
        _swept_fields("OUTBOUND"),
    ),
    ("IN", smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR"), _swept_fields("INBOUND")),
]

# Reads the sweep must issue, from the map rather than from the loop's own
# lists. 2 clock-gate accesses + the sweep + 1 restore.
EXPECTED_ACCESSES = 3 + sum(_MAILBOX_COUNT * len(f) for _, _, f in _PORTS)


class smc_mailbox_field_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", _CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", _CLOCK_GATE_CONTROL, cg | _MAILBOX_CG_EN)
        for port, base, fields in _PORTS:
            for i in range(_MAILBOX_COUNT):
                for name, off in fields:
                    addr = base + i * _MAILBOX_STRIDE + off
                    await self.csr_read(f"MBOX_{port}_{i}_{name}", addr)
        cocotb.log.info(
            "CHK-MBOX-FIELD-DECODE: every one of the %d field reads returned OKAY "
            "across %d mailboxes on %d ports",
            EXPECTED_ACCESSES - 3,
            _MAILBOX_COUNT,
            len(_PORTS),
        )
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", _CLOCK_GATE_CONTROL, cg)
        assert self.accesses == EXPECTED_ACCESSES, (
            f"mailbox field sweep mismatch: got {self.accesses}, expected "
            f"{EXPECTED_ACCESSES} -- one read per readable register of "
            f"{_MAILBOX_COUNT} mailboxes on each of {len(_PORTS)} ports, counted "
            f"from the generated map"
        )
        cocotb.log.info(
            "CHK-MBOX-FIELD-COUNT: %d accesses, matching the register count the "
            "generated map holds rather than the length of any list this "
            "testcase owns",
            EXPECTED_ACCESSES,
        )
