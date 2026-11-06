# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratchpad bank and entry selection, graded at the bank ports and in the macros.

cpu.adoc, "Memory System": "The scratchpad occupies `0xC006_0000` to `0xC015_FFFF` as
eight contiguous 128 KiB groups of four banks. Within a group, consecutive 64-byte
stripes rotate across the group's four banks. For a byte offset from the scratchpad
base, the bank and the 64-bit entry within that bank are: bank = 4 * offset[19:17] +
offset[7:6]; entry = {offset[16:8], offset[5:3]}. Each bank holds 4096 entries (32
KiB), and the bank number is the index of the bank's memory interface port at the SMC
boundary."

With the four cores held (a core reset leaves the boundary connected), a distinct word
is written over SEP_IN at every offset of a walk that toggles each bank bit and each
entry bit alone from offset 0, lands on entries 4088 and 4095 of bank 31 and on the
last entry before a group boundary. Each word is read back through SEP_IN with the 32
per-bank read counters snapshotted around the read: only the counter at
`4 * offset[19:17] + offset[7:6]` advances. The macro word at entry
`{offset[16:8], offset[5:3]}` of that bank, read through `tb_cpu_scratch_peek_data`,
is the word written at the offset.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import SPM_MEMORY_BASE, cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_scratch_residency_utils import scratch_banks_read, snapshot_scratch_bank_reads

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
CORE_RESET_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
_CORES_HELD_BOUND = 200

# Each bank bit (offset[7:6], offset[19:17]) and each entry bit (offset[5:3],
# offset[16:8]) toggled alone from offset 0, bank 31 at entries 4088 and 4095, and the
# last entry of bank 3 before the first group boundary.
OFFSETS = (
    0x0,
    0x8,
    0x10,
    0x20,
    0x40,
    0x80,
    0xC0,
    0x100,
    0x200,
    0x400,
    0x800,
    0x1000,
    0x2000,
    0x4000,
    0x8000,
    0x1_0000,
    0x1_FFF8,
    0x2_0000,
    0x4_0000,
    0x8_0000,
    0xE_0000,
    0xF_FFC0,
    0xF_FFF8,
)
ENTRIES_PER_BANK = 4096
BANKS = 32


def bank_of(offset: int) -> int:
    return 4 * ((offset >> 17) & 0x7) + ((offset >> 6) & 0x3)


def entry_of(offset: int) -> int:
    return (((offset >> 8) & 0x1FF) << 3) | ((offset >> 3) & 0x7)


def word_at(offset: int) -> int:
    return (0xC0DE << 48) | (offset << 16) | (OFFSETS.index(offset) + 1)


class smc_spm_bank_formula_test_seq(SmcCsrSeq):
    """Write the walk, read it back under the bank counters, peek each macro word."""

    def __init__(self, name: str = "smc_spm_bank_formula_test_seq") -> None:
        super().__init__(name)
        self.bank_rows: list[tuple[int, int, int]] = []
        self.entry_rows: list[tuple[int, int, int]] = []

    async def _wait_core_resets(self, want: int, label: str) -> None:
        dut = cocotb.top
        for _ in range(_CORES_HELD_BOUND):
            await ClockCycles(dut.clk_smc_i, 1)
            if int(dut.tb_cpu_core_resets_n.value) == want:
                return
        raise AssertionError(
            f"{label}: tb_cpu_core_resets_n did not read 0x{want:x} within {_CORES_HELD_BOUND} "
            f"clk_smc_i cycles (last 0x{int(dut.tb_cpu_core_resets_n.value):x})"
        )

    async def _peek(self, offset: int) -> int:
        dut = cocotb.top
        dut.tb_cpu_scratch_peek_offset.value = offset
        await ClockCycles(dut.clk_smc_i, 2)
        return int(dut.tb_cpu_scratch_peek_data.value)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        banks = {bank_of(o) for o in OFFSETS}
        entries = {entry_of(o) for o in OFFSETS}
        assert len(set(OFFSETS)) == len(OFFSETS) and max(entries) == ENTRIES_PER_BANK - 1, (
            f"walk offsets {OFFSETS} do not reach entry {ENTRIES_PER_BANK - 1}"
        )
        assert all(b < BANKS for b in banks) and {0, 1, 2, 3, 4, 8, 16, 28, 31} <= banks, (
            f"walk banks {sorted(banks)} do not toggle every bank bit"
        )

        reset_ctrl = await self.csr_read("RESET_CTRL_SAVE", RESET_CTRL, length=8)
        await self.csr_write(
            "RESET_CTRL_HOLD_CORES", RESET_CTRL, reset_ctrl & ~CORE_RESET_N, length=8
        )
        await self._wait_core_resets(0, "cores held")
        try:
            for offset in OFFSETS:
                await self.csr_write(
                    "SPM_FORMULA_WRITE", SPM_MEMORY_BASE + offset, word_at(offset), length=8
                )

            for offset in OFFSETS:
                before = snapshot_scratch_bank_reads()
                await self.csr_read(
                    "SPM_FORMULA_READ", SPM_MEMORY_BASE + offset, length=8, expected=word_at(offset)
                )
                touched = scratch_banks_read(before, snapshot_scratch_bank_reads())
                bank = bank_of(offset)
                assert set(touched) == {bank} and touched[bank] >= 1, (
                    f"a read at offset 0x{offset:x} advanced bank read counters {touched}, "
                    f"expected only bank {bank} = 4 * {(offset >> 17) & 7} + {(offset >> 6) & 3}"
                )
                self.bank_rows.append((offset, bank, touched[bank]))
            cocotb.log.info(
                "CHK-SPM-BANK-SELECT-FORMULA: %d SEP_IN reads over offsets toggling every bit of "
                "offset[19:17] and offset[7:6]: for each, tb_cpu_scratch_bank_read_count[4 * "
                "offset[19:17] + offset[7:6]] alone advanced and the other %d counters held "
                "(offset, bank, reads): %s",
                len(self.bank_rows),
                BANKS - 1,
                ", ".join(f"(0x{o:x}, {b}, {n})" for o, b, n in self.bank_rows),
            )

            for offset in OFFSETS:
                got = await self._peek(offset)
                assert got == word_at(offset), (
                    f"the macro word at bank {bank_of(offset)} entry {entry_of(offset)} reads "
                    f"0x{got:016x}, not the 0x{word_at(offset):016x} written at offset "
                    f"0x{offset:x}: the entry is not {{offset[16:8], offset[5:3]}}"
                )
                self.entry_rows.append((offset, bank_of(offset), entry_of(offset)))
            cocotb.log.info(
                "CHK-SPM-ENTRY-SELECT-FORMULA: %d distinct words written over SEP_IN each read "
                "back equal and each found in the macro word at entry {offset[16:8], "
                "offset[5:3]} of bank(offset) through tb_cpu_scratch_peek_data, with every entry "
                "bit toggled alone and entries %d and %d of bank 31 (offset, bank, entry): %s",
                len(self.entry_rows),
                ENTRIES_PER_BANK - 8,
                ENTRIES_PER_BANK - 1,
                ", ".join(f"(0x{o:x}, {b}, {e})" for o, b, e in self.entry_rows),
            )
        finally:
            await self.csr_write("RESET_CTRL_RELEASE_CORES", RESET_CTRL, reset_ctrl, length=8)
        await self._wait_core_resets(0xF, "cores released")
        await self.csr_read("RESET_CTRL_RESTORED", RESET_CTRL, length=8, expected=reset_ctrl)
