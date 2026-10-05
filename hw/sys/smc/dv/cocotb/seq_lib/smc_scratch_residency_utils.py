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

# The SMC CPU spec (hw/sys/smc/doc/cpu.adoc, "Local SRAM/Scratchpad: 1 MiB
# (32 banks)") fixes the scratch geometry; `tb_cpu_scratch_bank_read_count`
# carries one 32-bit counter per bank, so its width must agree with it.
SCRATCH_BANK_COUNT = 32
_BANK_COUNTER_WIDTH = 32
_BANK_COUNTER_MASK = (1 << _BANK_COUNTER_WIDTH) - 1

# The hello_world link map (sram.ld ORIGIN 0xC006_0000, 4 KB stacks and 2 KB
# heap from toolchain.mk) ends at offset 0x8730, inside the first 128 KiB group.
# The SMC CPU spec fixes the bank count and no specification states the
# interleave; the DV-owned table in `hw/sys/smc/dv/models/smc_scratch_map_pkg.sv`
# (measured against the design by `smc_dual_axi_sram_probe_test`) places that
# group in banks 0-3 and, because the footprint spans more than one stripe
# cycle, in all four of them.
HELLO_WORLD_RESIDENT_BANKS = frozenset(range(4))


def scratch_bank_count() -> int:
    """Return the spec's bank count after checking the counter port is sized for it."""
    width = len(cocotb.top.tb_cpu_scratch_bank_read_count)
    assert width == SCRATCH_BANK_COUNT * _BANK_COUNTER_WIDTH, (
        f"tb_cpu_scratch_bank_read_count is {width} bits wide, not {SCRATCH_BANK_COUNT} "
        f"banks x {_BANK_COUNTER_WIDTH}-bit counters: the bound model's scratch geometry "
        "disagrees with the spec, so the per-bank slicing would mis-read"
    )
    return SCRATCH_BANK_COUNT


def snapshot_scratch_bank_reads() -> tuple[int, ...]:
    """Return the per-bank scratch read counters, index = bank number."""
    packed = int(cocotb.top.tb_cpu_scratch_bank_read_count.value)
    return tuple(
        (packed >> (bank * _BANK_COUNTER_WIDTH)) & _BANK_COUNTER_MASK
        for bank in range(scratch_bank_count())
    )


def scratch_banks_read(before: tuple[int, ...], after: tuple[int, ...]) -> dict[int, int]:
    """Map each bank whose read counter advanced to the number of new reads."""
    assert len(before) == len(after), (
        f"bank snapshots differ in size: {len(before)} vs {len(after)}"
    )
    return {
        bank: after[bank] - before[bank]
        for bank in range(len(before))
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
