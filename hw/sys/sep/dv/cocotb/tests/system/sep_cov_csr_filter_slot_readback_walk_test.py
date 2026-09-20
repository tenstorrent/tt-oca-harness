# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read every filter slot back while it holds a walked pattern.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the AXI-Lite READ RESPONSE path of the 48 filter slices in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv` --
`gen_outbound_filter_reg[*].filter_reg_resp.r.data`,
`gen_inbound_filter_reg[*].filter_reg_resp.r.data`,
`outbound_filter_axil_resps[*].r.data`, `inbound_filter_axil_resps[*].r.data`
and the `sep_system_csr_axil_resps[*].r.data` they feed, plus the read-select
lanes `outbound_filter_axil_reqs[*].ar.addr[4:2]` and
`inbound_filter_axil_reqs[*].ar.addr[4:2]`.

`sep_cov_csr_filter_slot_data_walk_test` already walks patterns into every
slot, but `SepCovStim.word_walk` (`seq_lib/sep_cov_stimulus_seq.py`) is
write-only, so no slot is ever read while it holds a non-reset value. The read
data lanes therefore stay at their reset value for the whole run: the merged
report shows `filter_reg_resp.r.data[63:24]` untoggled on every slot. This
leaf is the read half of that walk; it does not replace the write walk, whose
write-side coverage it repeats only incidentally.

Stimulus: for each of the 32 outbound and 16 inbound slots, and for each
32-bit word of START_ADDR, END_ADDR and FILTER_CONFIG, write a pattern and
then read the same word back. The pattern set, the FILTER_CONFIG high-word
mask that keeps FILTER_CONFIG.locked[63] (write-once-set) clear, and the
trailing all-zero pattern that returns the slot to its reset value are the
ones `sep_cov_csr_filter_slot_data_walk_test` uses, so this leaf leaves the
bank in the same state that one does.

The read value is not compared against anything. `SepAxiRegDriver._rd` raises
only on a non-OKAY response, which says the access did not reach the slot.

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
class sep_cov_csr_filter_slot_readback_walk_test(sep_base_test):
    """Write-then-read pattern walk across all 48 filter slots. Stimulus only."""

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
                    await self._walk_and_read(stim, slot + offset, WALK_PATTERNS)
                    await self._walk_and_read(stim, slot + offset + 4, WALK_PATTERNS)
                await self._walk_and_read(stim, slot + FILTER_CONFIG, WALK_PATTERNS)
                await self._walk_and_read(stim, slot + FILTER_CONFIG + 4, CONFIG_HI_PATTERNS)
            self.logger.info("%s filter write+read walk driven over %d slots", bank, count)

    async def _walk_and_read(self, stim: SepCovStim, addr: int, patterns) -> None:
        """Write each pattern to one CSR word and read the word back.

        The read value is logged and dropped; nothing here expects a value.
        """
        for pattern in patterns:
            await stim._wr(addr, pattern)
            await stim._rd(addr)
