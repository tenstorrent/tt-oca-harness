# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SS_COLD_RESET_LOCK: write-one-to-set, and it masks the reset it guards.

No enrolled testcase reads `RESET_UNIT.SS_COLD_RESET_LOCK`. The gap came out of
the porting necessity analysis: `cold_reset_lock_sanity` in `fw/tests/` is the
only thing in the tree that touches it, and rather than port a firmware image
this covers the same two properties natively, where SEP_IN AXI already reaches
the reset unit.

The register semantics are taken from the RDL, not assumed.
`hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl:87-95` declares
`cold_reset_lock[31:0]` as `sw = rw; hw = r; onwrite = woset;` with reset 0, one
bit per subsystem. Two consequences are worth a test:

**The lock is sticky.** `woset` means a written 1 sets and a written 0 does
nothing, so software cannot release a lock it has taken. Writing all-zeroes
must leave a set bit set. A register that cleared would let anything that can
write once also undo the guard.

**The lock masks the reset it guards.** `smc_subsystem_resets.sv` gates
`SS_COLD_RESET_N` writes with `~ss_cold_reset_lock`. `cool_reset_isolate_cfg`
records the same fact from the other side, as its reason for *not* comparing
`SS_COLD_RESET_N` — so the masking is asserted here and nowhere else.

Two things stop the masking leg passing for the wrong reason:

* `SS_COLD_RESET_N` is proved writable *before* any bit is locked. Without
  that, "the locked bit did not change" is satisfied by a register that never
  changes ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
* The masked write carries an **unlocked** bit alongside the locked one, and
  that bit is required to change. So "unchanged" cannot be explained by the
  write having been dropped on the floor.

This testcase locks one bit for the remainder of its simulation, which is what
`woset` means. Each testcase runs its own simulation, so nothing else sees it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SS_COLD_RESET_N = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR")
SS_COLD_RESET_LOCK = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR")

# Bit 0 stays unlocked and is the control that proves the write landed; bit 1
# is the one put under the lock.
_FREE_BIT = 0
_LOCKED_BIT = 1
_FREE = 1 << _FREE_BIT
_LOCKED = 1 << _LOCKED_BIT


class smc_cold_reset_lock_test_seq(SmcCsrSeq):
    """The cold-reset lock sets once and gates the reset register."""

    def __init__(self, name: str = "smc_cold_reset_lock_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def body(self) -> None:
        # ---- Preconditions --------------------------------------------------
        lock0 = await self.csr_read("COLD_RESET_LOCK_PRE", SS_COLD_RESET_LOCK)
        assert (lock0 & (_FREE | _LOCKED)) == 0, (
            f"SS_COLD_RESET_LOCK already holds one of the bits under test "
            f"(0x{lock0:08x}); `woset` means it cannot be cleared, so neither leg "
            f"below could be attributed to this sequence"
        )

        # ---- Positive control: the reset register is writable at all --------
        await self.csr_write("COLD_RESET_N_ARM", SS_COLD_RESET_N, _FREE)
        armed = await self.csr_read("COLD_RESET_N_ARM_RB", SS_COLD_RESET_N)
        assert (armed & (_FREE | _LOCKED)) == _FREE, (
            f"arm: SS_COLD_RESET_N read 0x{armed:08x} after writing "
            f"0x{_FREE:08x} with nothing locked. The masking leg below needs this "
            f"register to be writable before a lock is taken, or 'unchanged' "
            f"proves nothing"
        )
        cocotb.log.info(
            "CHK-COLD-RESET-LOCK-ARM: SS_COLD_RESET_N accepted 0x%08x with "
            "SS_COLD_RESET_LOCK=0x%08x, so it is writable before any lock",
            _FREE,
            lock0,
        )
        self.chk_seen.add("CHK-COLD-RESET-LOCK-ARM")

        # ---- woset: a written 1 sets, a written 0 does nothing --------------
        await self.csr_write("COLD_RESET_LOCK_SET", SS_COLD_RESET_LOCK, _LOCKED)
        locked = await self.csr_read("COLD_RESET_LOCK_SET_RB", SS_COLD_RESET_LOCK)
        assert (locked & _LOCKED) == _LOCKED, (
            f"SS_COLD_RESET_LOCK read 0x{locked:08x} after writing 0x{_LOCKED:08x}; "
            f"reset_unit.rdl:87-95 declares the field sw=rw with onwrite=woset, so "
            f"the bit should have set"
        )
        await self.csr_write("COLD_RESET_LOCK_CLEAR_ATTEMPT", SS_COLD_RESET_LOCK, 0)
        still = await self.csr_read("COLD_RESET_LOCK_CLEAR_RB", SS_COLD_RESET_LOCK)
        assert (still & _LOCKED) == _LOCKED, (
            f"CHK-COLD-RESET-LOCK-WOSET: SS_COLD_RESET_LOCK read 0x{still:08x} "
            f"after an all-zeroes write, losing bit {_LOCKED_BIT}. "
            f"reset_unit.rdl:92 sets onwrite=woset, so a written 0 must be a "
            f"no-op — software cannot release a cold-reset lock it has taken"
        )
        cocotb.log.info(
            "CHK-COLD-RESET-LOCK-WOSET: bit %d set on a 0x%08x write and survived "
            "an all-zeroes write (0x%08x -> 0x%08x)",
            _LOCKED_BIT,
            _LOCKED,
            locked,
            still,
        )
        self.chk_seen.add("CHK-COLD-RESET-LOCK-WOSET")

        # ---- The lock masks SS_COLD_RESET_N --------------------------------
        # One write carries both bits. The locked one must not change; the
        # unlocked one must, which is what proves the write reached the
        # register rather than being dropped.
        await self.csr_write("COLD_RESET_N_MASKED", SS_COLD_RESET_N, _FREE | _LOCKED)
        after = await self.csr_read("COLD_RESET_N_MASKED_RB", SS_COLD_RESET_N)
        assert (after & _LOCKED) == 0, (
            f"CHK-COLD-RESET-LOCK-MASKS-WRITE: SS_COLD_RESET_N bit {_LOCKED_BIT} "
            f"became set (read 0x{after:08x}) even though SS_COLD_RESET_LOCK holds "
            f"0x{still:08x}. smc_subsystem_resets.sv gates the write with "
            f"~ss_cold_reset_lock, so a locked bit must not follow software"
        )
        assert (after & _FREE) == _FREE, (
            f"CHK-COLD-RESET-LOCK-MASKS-WRITE: the unlocked control bit "
            f"{_FREE_BIT} is clear (read 0x{after:08x}), so the write did not "
            f"reach the register and the locked bit staying clear proves nothing"
        )
        cocotb.log.info(
            "CHK-COLD-RESET-LOCK-MASKS-WRITE: one write of 0x%08x left bit %d "
            "clear under the lock while bit %d followed it (read 0x%08x, "
            "lock=0x%08x)",
            _FREE | _LOCKED,
            _LOCKED_BIT,
            _FREE_BIT,
            after,
            still,
        )
        self.chk_seen.add("CHK-COLD-RESET-LOCK-MASKS-WRITE")
