# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Data walk over every inbound and outbound filter slot in sep_system_csr.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the replicated register slices `gen_outbound_filter_reg` and
`gen_inbound_filter_reg` in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv`, and the
`outbound_filter_ctrl_o` / `inbound_filter_ctrl_o` structs they drive. Today
`seq_lib/sep_fabric_csr_bank_seq.py` writes one index-derived value into the
low word of a couple of slots per seed, so the START_ADDR / END_ADDR upper
bits and the FILTER_CONFIG enables hold their reset value on every slot.

Stimulus: for each of the 32 outbound and 16 inbound slots, drive
0xFFFF_FFFF, 0x5555_5555, 0xAAAA_AAAA and 0x0000_0000 through both 32-bit
words of START_ADDR and END_ADDR and through FILTER_CONFIG. The FILTER_CONFIG
high word is masked so bit 31 -- FILTER_CONFIG.locked[63], write-once-set --
stays clear and the slot keeps accepting writes; the permanent lock is the
separate `sep_cov_csr_filter_lock_all_slots_test`. The walk ends on the
all-zero pattern, which returns every slot to its reset value.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import (
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_LOCK_HI_BIT,
    FILTER_START_ADDR,
    INFILT_ENTRIES,
    OUTFILT_ENTRIES,
    WALK_PATTERNS,
    SepCovStim,
)

# FILTER_CONFIG high word patterns with the write-once-set lock bit removed.
CONFIG_HI_PATTERNS = tuple(p & ~FILTER_LOCK_HI_BIT & 0xFFFF_FFFF for p in WALK_PATTERNS)


@pyuvm.test()
class sep_cov_csr_filter_slot_data_walk_test(sep_base_test):
    """Pattern walk across all 48 filter slots. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for inbound, count in ((False, OUTFILT_ENTRIES), (True, INFILT_ENTRIES)):
            bank = "inbound" if inbound else "outbound"
            for index in range(count):
                slot = stim.filter_slot(inbound=inbound, index=index)
                for offset in (FILTER_START_ADDR, FILTER_END_ADDR):
                    await stim.word_walk(slot + offset)
                    await stim.word_walk(slot + offset + 4)
                await stim.word_walk(slot + FILTER_CONFIG)
                await stim.word_walk(slot + FILTER_CONFIG + 4, CONFIG_HI_PATTERNS)
            self.logger.info("%s filter data walk driven over %d slots", bank, count)
