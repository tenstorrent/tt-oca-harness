# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The eFuse guard answering a software lock, on three shadow fields.

`hw/ip/efuse/doc/architecture.adoc` gives every shadow field a 4-bit `lock`
permission and two independent ways to reach it: hardware locks fused into the
array, and software locks written into the `LOCKS` CSR, which is
"write-1-to-set", so "firmware can tighten access at runtime but can never
loosen a restriction without a reset". The guard (`efuse_guard.sv`) enforces
whichever is more restrictive, and a locked access is answered rather than
executed -- the write does not land, and the read does not disclose.

`smc_efuse_locked_access_interrupt_test` drives that path on
`JTAG_PUBLIC_IDENTITY`, but it needs its own preload asset and is held out of
the regression, so in the scheduled run nothing establishes a software lock at
all. This leaf does it from the CSR side alone, on the default eFuse image, and
checks the guard's answer rather than any state change.

Three fields, each taken through the same four steps, and the first step is the
live control for the two that follow:

1. **Unlocked.** A pattern is written into the field and read back exactly, so
   the field is demonstrably writable and readable before anything is locked.
2. **Write-locked.** The field's write-lock bit is set in `LOCKS` and read
   back, then a different pattern is written. The write may be refused or
   ignored -- neither the RDL nor the architecture document fixes which, so the
   response is recorded rather than asserted -- but the field has to still read
   the pattern from step 1. That is the claim.
3. **Write-1-to-set.** `LOCKS` is written again with that bit clear. The RDL
   makes every lock `onwrite = woset`, so the bit has to stay set.
4. **Read-locked.** The field's read-lock bit is set, and the field is read.
   The architecture document states the permission (`lock[0] = 1` is
   read-locked) but not the word a read-locked shadow register substitutes, so
   the claim is non-disclosure: what comes back must not be the pattern the
   field holds.

The fields are the first two SPARE entries and the OCCP transport timeout,
whose locks the default image leaves clear -- the sequence reads `LOCKS` first
and fails if any of the six bits it is about to set is already set, so it never
mistakes a pre-set lock for one it established. `SMC_CONFIG` and
`JTAG_PUBLIC_IDENTITY` are deliberately left alone: the first carries boot
configuration other logic reads, and the second is the held-out leaf's subject.

A software lock is cleared only by reset, so this leaf leaves all six bits set
and is terminal for those three fields. Nothing else in the run reads them.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_efuse_map_u32, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import efuse_preload_word_at

LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
#: The LOCKS word the default eFuse image senses into the shadow register.
LOCKS_PRELOAD = efuse_preload_word_at(LOCKS)

_WORD_BYTES = 8


def _spare(index: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", index)


# (label, field address, write-lock mask, read-lock mask, pattern, second pattern).
# The two patterns of a field differ in every bit, so a write that half-landed
# is as visible as one that landed whole.
_FIELDS: tuple[tuple[str, int, int, int, int, int], ...] = (
    (
        "SPARE0",
        _spare(0),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE0_WRITE_LOCK_bm"),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE0_READ_LOCK_bm"),
        0xA5A5_5A5A_C0DE_0000,
        0x5A5A_A5A5_3F21_FFFF,
    ),
    (
        "SPARE1",
        _spare(1),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE1_WRITE_LOCK_bm"),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__SPARE1_READ_LOCK_bm"),
        0x1234_5678_C0DE_0001,
        0xEDCB_A987_3F21_FFFE,
    ),
    (
        "OCCP_TRANSPORT_TIMEOUT",
        smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR"),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__OCCP_TRANSPORT_TIMEOUT_WRITE_LOCK_bm"),
        smc_efuse_map_u32("SMC_EFUSE_MAP__LOCKS__OCCP_TRANSPORT_TIMEOUT_READ_LOCK_bm"),
        0x0F0F_F0F0_C0DE_0002,
        0xF0F0_0F0F_3F21_FFFD,
    ),
)

_ACCESSES_PER_FIELD = 11


class smc_efuse_lock_guard_test_seq(SmcCsrSeq):
    """Establish a software lock on three shadow fields and check the guard."""

    def __init__(self, name: str = "smc_efuse_lock_guard_test_seq") -> None:
        super().__init__(name)
        self.write_locks_held = 0
        self.read_locks_held = 0
        self.woset_proofs = 0
        #: Response code each write-locked write returned, in field order.
        self.locked_write_resps: list[int] = []
        #: Word each read-locked read returned, in field order.
        self.locked_read_data: list[int] = []

    async def _locked_write(self, label: str, addr: int, data: int) -> int:
        """A write the guard may refuse or ignore; the caller checks the state."""
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD_BYTES
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, (
            f"{label}: the write-locked write got no response at all, so the guard "
            f"wedged the bus instead of answering"
        )
        return item.resp_code

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        assert len({addr for _n, addr, *_ in _FIELDS}) == len(_FIELDS), (
            "two of the fields under test resolve to the same address"
        )
        about_to_set = 0
        for _name, _addr, wr_lock, rd_lock, *_ in _FIELDS:
            about_to_set |= wr_lock | rd_lock

        locks = await self.csr_read("LOCKS_PRE", LOCKS, expected=LOCKS_PRELOAD, length=_WORD_BYTES)
        assert locks & about_to_set == 0, (
            f"LOCKS reads 0x{locks:016x} before this sequence wrote anything, and "
            f"0x{locks & about_to_set:x} of the bits it is about to set is already set by the "
            f"eFuse image; a lock it did not establish would make the denies below prove "
            f"nothing about the CSR lock path"
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-GUARD-PRE: LOCKS reads the image word 0x%016x with every one of "
            "the %d lock bits this sequence establishes still clear, so each deny below "
            "follows a lock it set itself",
            locks,
            bin(about_to_set).count("1"),
        )

        for name, addr, wr_lock, rd_lock, pattern, other in _FIELDS:
            # 1. Unlocked: the live control for both denies.
            await self.csr_write(f"{name}_UNLOCKED_WR", addr, pattern, length=_WORD_BYTES)
            await self.csr_read(f"{name}_UNLOCKED_RD", addr, expected=pattern, length=_WORD_BYTES)

            # 2. Write lock.
            locks |= wr_lock
            await self.csr_write(f"{name}_WR_LOCK", LOCKS, locks, length=_WORD_BYTES)
            await self.csr_read(f"{name}_WR_LOCK_RB", LOCKS, expected=locks, length=_WORD_BYTES)
            resp = await self._locked_write(f"{name}_LOCKED_WR", addr, other)
            self.locked_write_resps.append(resp)
            held = await self.csr_read(
                f"{name}_AFTER_LOCKED_WR", addr, expected=pattern, length=_WORD_BYTES
            )
            assert held == pattern, (
                f"{name} @ 0x{addr:08x} reads 0x{held:016x} after a write of 0x{other:016x} "
                f"with its write lock set; the guard let the write land"
            )
            self.write_locks_held += 1

            # 3. Write-1-to-set: a write with the bit clear may not clear it.
            await self.csr_write(f"{name}_WOSET_TRY", LOCKS, locks & ~wr_lock, length=_WORD_BYTES)
            still = await self.csr_read(
                f"{name}_WOSET_RB", LOCKS, expected=locks, length=_WORD_BYTES
            )
            assert still & wr_lock == wr_lock, (
                f"{name}: LOCKS reads 0x{still:016x} after a write with its write-lock bit "
                f"clear; the RDL makes every lock `onwrite = woset`, so software cannot "
                f"loosen it"
            )
            self.woset_proofs += 1

            # 4. Read lock.
            locks |= rd_lock
            await self.csr_write(f"{name}_RD_LOCK", LOCKS, locks, length=_WORD_BYTES)
            await self.csr_read(f"{name}_RD_LOCK_RB", LOCKS, expected=locks, length=_WORD_BYTES)
            # No exact expectation: the architecture document states the
            # permission but not the word a read-locked field substitutes.
            disclosed = await self.csr_read(f"{name}_LOCKED_RD", addr, length=_WORD_BYTES)
            self.locked_read_data.append(disclosed)
            assert disclosed != pattern, (
                f"{name} @ 0x{addr:08x} returned 0x{disclosed:016x} with its read lock set, "
                f"which is the word the field holds; the read lock disclosed it"
            )
            self.read_locks_held += 1

        fields = len(_FIELDS)
        assert self.write_locks_held == fields and self.read_locks_held == fields, (
            f"{self.write_locks_held} write locks and {self.read_locks_held} read locks "
            f"enforced for {fields} fields"
        )
        assert self.woset_proofs == fields, (
            f"{self.woset_proofs} write-1-to-set proofs for {fields} fields"
        )
        self.assert_all_reachable(1 + fields * _ACCESSES_PER_FIELD, "EFUSE_LOCK_GUARD")

        cocotb.log.info(
            "CHK-EFUSE-LOCK-GUARD-WRITE: on %d shadow fields a pattern written while the "
            "field was unlocked read back exactly, and a different pattern written after "
            "the field's write lock was set in LOCKS did not land -- the field still read "
            "the first pattern. The guard answered each refused write (response code(s) "
            "%s) instead of wedging the bus",
            self.write_locks_held,
            ", ".join(str(r) for r in self.locked_write_resps),
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-GUARD-WOSET: on %d shadow fields a later write of LOCKS with "
            "the field's write-lock bit clear left it set, which is the `onwrite = woset` "
            "contract the RDL gives every lock and the reason software can tighten access "
            "but never loosen it without a reset",
            self.woset_proofs,
        )
        cocotb.log.info(
            "CHK-EFUSE-LOCK-GUARD-READ: on %d shadow fields a read taken after the field's "
            "read lock was set returned something other than the word the field holds "
            "(%s), so the guard withheld the content; the architecture document fixes the "
            "permission but not the substituted word, so non-disclosure is the whole claim",
            self.read_locks_held,
            ", ".join(f"0x{d:016x}" for d in self.locked_read_data),
        )
