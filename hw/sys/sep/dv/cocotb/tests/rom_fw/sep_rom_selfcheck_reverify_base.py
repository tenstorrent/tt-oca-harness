# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The self-check re-verifies the manifest locus and the fuse-secret locks on its own.

rom.adoc, Pre-Hand-off Self-Check (Gate Ledger):

* SEP-ROM-HOFF-050: "The self-check shall additionally re-verify, twice each over
  independently evaluated (optimizer-opaque) operands: the manifest locus (the validated
  manifest sits at the SEP SRAM base, within range) and the fuse-secret lock state. ... Any
  shortfall or disagreement is fatal (`ROM_ERR_HANDOFF_SELFCHECK_FAILED`, `0xF004`)."
* "The manifest locus holds when `bl0_state.sep_sram_manifest_addr` equals the SEP SRAM base
  and that base plus the validated manifest length does not pass the end of SEP SRAM."
* "The fuse-secret lock state holds when a fresh read of `SEP_EFUSE_MAP_LOCKS` has all six
  read-lock bits of SEP-ROM-HOFF-030 set."

Every gate stamp still retires in these leaves, so the ledger compare passes and only the
re-verification can halt the boot.

* Address: once MEAS_BOOT_STATE_OK ([S27], after [S23] recorded the manifest) is on the
  console, an ECC-consistent DCCM flip moves the recorded manifest address off the SRAM base.
  The field's address is the one the first locus check loads.
* Length: the same flip on the ROM-private validated manifest length adds 0x4_0000 (the SEP
  SRAM size), so base plus length passes the end of SRAM.
* Locks: after DMA_INIT_OK the [S25] lock write is replaced by a nop and the [S26] branch on
  check_fuse_secrets_locked() by an unconditional jump to its pass path; the [S26] re-read
  still runs and prints FUSE_SECRETS_NOT_LOCKED, and the FUSELOCK stamp retires.

Checks: CHK-FAULT-TOOK-EFFECT (the locus held before the flip, the DCCM read-back is the
recorded value with the flipped bits, and only the faulted leg of the locus rule now fails; or
the replaced instructions retired and [S26] printed
FUSE_SECRETS_NOT_LOCKED), CHK-ALL-STAMPS (all four gates' stores retired after the reset), and
the halt contract with the halt at the first evaluation of the faulted check.
"""

from __future__ import annotations

from env.sep_rv32_trace_decode import OP_LOAD, opcode
from rom_fw.sep_rom_gate_ledger_base import (
    AFTER_S23_LINE,
    GATES,
    INSN_NOP,
    OP_BRANCH,
    dccm_word,
    jump,
    sep_rom_gate_ledger_base,
)
from sep_reg_meta import sym

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
# STATUS_ENCODE(ERROR, BL0 1, FUSE_SECRETS_NOT_LOCKED): the [S26] failure report.
STATUS_FUSE_NOT_LOCKED = 0x0F01_021D


def manifest_addr_field(rom) -> int:
    """DCCM address of bl0_state.sep_sram_manifest_addr, as check_locus_first loads it."""
    length = rom.syms["g_gate_manifest_len"]
    loads = [
        i.mem
        for i in rom.scan("check_locus_first")
        if opcode(i.word) == OP_LOAD and i.mem is not None and i.mem != length
    ]
    assert len(loads) == 1, f"check_locus_first loads {loads} besides the manifest length"
    return loads[0]


class sep_rom_locus_flip_base(sep_rom_gate_ledger_base):
    """Flips one locus word in DCCM after [S23]; subclasses name the word and the bits."""

    data_mask = 0
    breaks_addr = False

    def target(self) -> int:
        raise NotImplementedError

    def locus(self) -> tuple[int, int]:
        """(recorded manifest address, validated manifest length) as DCCM holds them now."""
        return dccm_word(manifest_addr_field(self.img)), dccm_word(
            self.img.syms["g_gate_manifest_len"]
        )

    async def inject(self, obs) -> None:
        await self.wait_line(obs, AFTER_S23_LINE)
        self.before_locus = self.locus()
        self.before, _ = await self.dccm_flip(self.target(), self.data_mask)

    def grade(self, obs, chk) -> None:
        before = getattr(self, "before", None)
        pre = getattr(self, "before_locus", None)
        now = dccm_word(self.target())
        addr, length = self.locus()
        recorded = None if before is None else before & 0xFFFF_FFFF
        # Only the faulted leg of the locus rule may fail, and the rule held before the flip.
        addr_ok, len_ok = addr == SRAM_BASE, length <= SRAM_BASE + SRAM_SIZE - addr
        broken = (not addr_ok and len_ok) if self.breaks_addr else (addr_ok and not len_ok)
        chk.ok(
            "FAULT-TOOK-EFFECT",
            recorded is not None
            and pre is not None
            and pre[0] == SRAM_BASE
            and pre[1] <= SRAM_SIZE
            and now == recorded ^ self.data_mask
            and broken,
            word=f"0x{self.target():08x}",
            recorded=f"0x{recorded:08x}" if recorded is not None else "none",
            readback=f"0x{now:08x}",
            before_addr=f"0x{pre[0]:08x}" if pre else "none",
            before_len=f"0x{pre[1]:08x}" if pre else "none",
            manifest_addr=f"0x{addr:08x}",
            manifest_len=f"0x{length:08x}",
        )
        reset_t = self.last_reset_t(obs)
        stamps = {g: self.stamps_retired(obs, g, reset_t) for g in GATES}
        chk.ok("ALL-STAMPS", all(stamps.values()), **stamps)
        self.grade_halt(obs, chk, kind="eval", check="check_locus_first")


def lock_fault_edits(rom) -> dict[int, int]:
    """Replace the [S25] lock write with a nop and make the [S26] branch take its pass path."""
    write = rom.calls("lock_fuse_secrets")
    check = rom.calls("check_fuse_secrets_locked")
    assert len(write) == 1 and len(check) == 1, f"lock calls {write}, check calls {check}"
    body = rom.scan_range(check[0] + 4, check[0] + 4 + 64)
    branch = next(i for i in body if opcode(i.word) == OP_BRANCH)
    # The fall-through is the failure path when it reports FUSE_SECRETS_NOT_LOCKED.
    fall = rom.scan_range(branch.pc + 4, branch.pc + 4 + 16)
    fails_on_fall = any(i.value == STATUS_FUSE_NOT_LOCKED for i in fall)
    edits = {write[0]: INSN_NOP}
    edits[branch.pc] = jump(branch.pc, branch.target) if fails_on_fall else INSN_NOP
    return edits
