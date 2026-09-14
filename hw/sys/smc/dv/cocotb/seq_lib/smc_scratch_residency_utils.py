# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Scratch-bank residency evidence for a CPU image booted from scratch RAM.

The bound `smc_cpu_mem_dv` model counts reads per scratch bank on the bank
ports the CPU cluster drives. Snapshot the counters before the cores are
released and again after the firmware's verdict is read back: the banks whose
counters moved are the banks the CPU actually fetched from, so a residency
claim about the image becomes a compare of that set against the banks the
plan says the image occupies rather than a statement about how it was loaded.
"""

from __future__ import annotations

from collections.abc import Iterable

import cocotb

SCRATCH_BANK_COUNT = 32
_BANK_COUNTER_WIDTH = 32
_BANK_COUNTER_MASK = (1 << _BANK_COUNTER_WIDTH) - 1

# The hello_world link map (sram.ld ORIGIN 0xC006_0000, 4 KB stacks and 2 KB
# heap from toolchain.mk) ends at offset 0x8730, inside the first 128 KB group;
# smc_scratch_map_pkg maps that group to banks 0-3 and, because the footprint
# spans more than one 256-byte stripe cycle, to all four of them.
HELLO_WORLD_RESIDENT_BANKS = frozenset(range(4))


def snapshot_scratch_bank_reads() -> tuple[int, ...]:
    """Return the per-bank scratch read counters, index = bank number."""
    packed = int(cocotb.top.tb_cpu_scratch_bank_read_count.value)
    return tuple(
        (packed >> (bank * _BANK_COUNTER_WIDTH)) & _BANK_COUNTER_MASK
        for bank in range(SCRATCH_BANK_COUNT)
    )


def scratch_banks_read(before: tuple[int, ...], after: tuple[int, ...]) -> dict[int, int]:
    """Map each bank whose read counter advanced to the number of new reads."""
    return {
        bank: after[bank] - before[bank]
        for bank in range(SCRATCH_BANK_COUNT)
        if after[bank] != before[bank]
    }


def check_scratch_residency(
    before: tuple[int, ...],
    after: tuple[int, ...],
    allowed_banks: Iterable[int],
) -> dict[int, int]:
    """Require every new scratch read to land in ``allowed_banks``.

    Fails when any bank outside the allowed set was read, and when no allowed
    bank was read at all (the image was never fetched, so there is nothing to
    call resident). Returns the per-bank read deltas for the log line.
    """
    allowed = frozenset(allowed_banks)
    touched = scratch_banks_read(before, after)
    outside = {bank: n for bank, n in touched.items() if bank not in allowed}
    inside = {bank: n for bank, n in touched.items() if bank in allowed}
    assert not outside, (
        "scratch reads outside the banks the image is resident in: "
        f"banks {sorted(outside)} took {sum(outside.values())} reads "
        f"(allowed banks {sorted(allowed)}, per-bank reads {touched})"
    )
    assert inside, (
        f"no scratch bank in {sorted(allowed)} was read between core release "
        "and the firmware verdict"
    )
    return touched
