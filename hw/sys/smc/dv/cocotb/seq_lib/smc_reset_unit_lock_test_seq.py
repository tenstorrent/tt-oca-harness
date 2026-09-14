# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reset unit's two woset lock registers: sticky, and they mask their target.

`RESET_UNIT.SS_COLD_RESET_LOCK` and `RESET_UNIT.SS_CONFIG_LOCK` are covered
natively over SEP_IN AXI, which reaches the reset unit without a firmware image
(`fw/tests/cold_reset_lock_sanity` exercises the cold-reset lock from firmware).

The semantics come from the RDL and the RTL. Both lock fields
are `sw = rw; hw = r; onwrite = woset;` with reset 0, one bit per subsystem
(`reset_unit.rdl:18-26` and `:87-95`), and both are consumed the same way in
`smc_subsystem_resets.sv`:

    config_filtered_wr_mask = (~ss_config_lock) & ss_config_wr_mask     (:81)
    ... the same gate on SS_COLD_RESET_N with ~ss_cold_reset_lock

Two consequences hold for both pairs, so one sequence covers both:

**The lock is sticky.** `woset` means a written 1 sets and a written 0 does
nothing, so software cannot release a lock it has taken. A register that
cleared would let anything that can write once also undo the guard.

**The lock masks its target register.** For the cold-reset pair,
`cool_reset_isolate_cfg` records the same fact from the other side, as its
reason for *not* comparing `SS_COLD_RESET_N` -- so the masking is asserted here
and nowhere else.

Two things stop the masking leg passing for the wrong reason:

* The target is proved writable *before* any bit is locked. Without that, "the
  locked bit did not change" is satisfied by a register that never changes
  ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
* The masked write carries an **unlocked** bit alongside the locked one, and
  that bit is required to change. So "unchanged" cannot be explained by the
  write having been dropped on the floor.

This testcase locks one bit of each register for the remainder of its
simulation, which is what `woset` means. Each testcase runs its own simulation,
so nothing else sees it.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# (label, target register, lock register, RDL citation for the lock field)
LOCK_PAIRS = [
    (
        "COLD_RESET",
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_N_BASE_ADDR"),
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_COLD_RESET_LOCK_BASE_ADDR"),
        "reset_unit.rdl:87-95",
    ),
    (
        "CONFIG",
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR"),
        smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR"),
        "reset_unit.rdl:18-26",
    ),
]

# Bit 0 stays unlocked and is the control that proves the write landed; bit 1
# is the one put under the lock.
_FREE_BIT = 0
_LOCKED_BIT = 1
_FREE = 1 << _FREE_BIT
_LOCKED = 1 << _LOCKED_BIT


class smc_reset_unit_lock_test_seq(SmcCsrSeq):
    """Each woset lock sets once and gates the register it guards."""

    def __init__(self, name: str = "smc_reset_unit_lock_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()

    async def _check_pair(self, label: str, target: int, lock: int, rdl: str) -> None:
        # ---- Preconditions --------------------------------------------------
        lock0 = await self.csr_read(f"{label}_LOCK_PRE", lock)
        assert (lock0 & (_FREE | _LOCKED)) == 0, (
            f"{label}: the lock register already holds one of the bits under test "
            f"(0x{lock0:08x}); `woset` means it cannot be cleared, so neither leg "
            f"below could be attributed to this sequence"
        )

        # ---- Positive control: the target is writable at all ----------------
        await self.csr_write(f"{label}_TARGET_ARM", target, _FREE)
        armed = await self.csr_read(f"{label}_TARGET_ARM_RB", target)
        assert (armed & (_FREE | _LOCKED)) == _FREE, (
            f"CHK-RESET-LOCK-ARM[{label}]: the target read 0x{armed:08x} after "
            f"writing 0x{_FREE:08x} with nothing locked. The masking leg below "
            f"needs this register writable before a lock is taken, or 'unchanged' "
            f"proves nothing"
        )
        cocotb.log.info(
            "CHK-RESET-LOCK-ARM[%s]: the target accepted 0x%08x with the lock at "
            "0x%08x, so it is writable before any lock",
            label,
            _FREE,
            lock0,
        )
        self.chk_seen.add(f"CHK-RESET-LOCK-ARM[{label}]")

        # ---- woset: a written 1 sets, a written 0 does nothing --------------
        await self.csr_write(f"{label}_LOCK_SET", lock, _LOCKED)
        locked = await self.csr_read(f"{label}_LOCK_SET_RB", lock)
        assert (locked & _LOCKED) == _LOCKED, (
            f"{label}: the lock read 0x{locked:08x} after writing 0x{_LOCKED:08x}; "
            f"{rdl} declares the field sw=rw with onwrite=woset, so the bit should "
            f"have set"
        )
        await self.csr_write(f"{label}_LOCK_CLEAR_ATTEMPT", lock, 0)
        still = await self.csr_read(f"{label}_LOCK_CLEAR_RB", lock)
        assert (still & _LOCKED) == _LOCKED, (
            f"CHK-RESET-LOCK-WOSET[{label}]: the lock read 0x{still:08x} after an "
            f"all-zeroes write, losing bit {_LOCKED_BIT}. {rdl} sets onwrite=woset, "
            f"so a written 0 must be a no-op -- software cannot release a lock it "
            f"has taken"
        )
        cocotb.log.info(
            "CHK-RESET-LOCK-WOSET[%s]: bit %d set on a 0x%08x write and survived an "
            "all-zeroes write (0x%08x -> 0x%08x)",
            label,
            _LOCKED_BIT,
            _LOCKED,
            locked,
            still,
        )
        self.chk_seen.add(f"CHK-RESET-LOCK-WOSET[{label}]")

        # ---- The lock masks its target --------------------------------------
        # One write carries both bits. The locked one must not change; the
        # unlocked one must, which is what proves the write reached the
        # register rather than being dropped.
        await self.csr_write(f"{label}_TARGET_MASKED", target, _FREE | _LOCKED)
        after = await self.csr_read(f"{label}_TARGET_MASKED_RB", target)
        assert (after & _LOCKED) == 0, (
            f"CHK-RESET-LOCK-MASKS-WRITE[{label}]: target bit {_LOCKED_BIT} became "
            f"set (read 0x{after:08x}) even though the lock holds 0x{still:08x}. "
            f"smc_subsystem_resets.sv gates the write with the inverted lock, so a "
            f"locked bit must not follow software"
        )
        assert (after & _FREE) == _FREE, (
            f"CHK-RESET-LOCK-MASKS-WRITE[{label}]: the unlocked control bit "
            f"{_FREE_BIT} is clear (read 0x{after:08x}), so the write did not reach "
            f"the register and the locked bit staying clear proves nothing"
        )
        cocotb.log.info(
            "CHK-RESET-LOCK-MASKS-WRITE[%s]: one write of 0x%08x left bit %d clear "
            "under the lock while bit %d followed it (read 0x%08x, lock=0x%08x)",
            label,
            _FREE | _LOCKED,
            _LOCKED_BIT,
            _FREE_BIT,
            after,
            still,
        )
        self.chk_seen.add(f"CHK-RESET-LOCK-MASKS-WRITE[{label}]")

    async def body(self) -> None:
        for label, target, lock, rdl in LOCK_PAIRS:
            await self._check_pair(label, target, lock, rdl)
        assert len(self.chk_seen) == 3 * len(LOCK_PAIRS), (
            f"only {len(self.chk_seen)} checkers ran over {len(LOCK_PAIRS)} lock "
            f"pairs: {sorted(self.chk_seen)}"
        )
