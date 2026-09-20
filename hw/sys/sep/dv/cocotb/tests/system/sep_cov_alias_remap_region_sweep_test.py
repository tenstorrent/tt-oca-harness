# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: all sixteen local-master alias-remap regions.

``axi_alias_remap`` holds sixteen regions and adds ``REGION_ATTRS.offset`` to
``addr[55:12]`` through a five-chunk carry-select adder. The suite programs one
region with one offset, so ``aw_remap_idx`` and ``ar_remap_idx`` carry one
value, the adder addend input sees a handful of bits, and the rest of the table
never leaves reset.

Two phases. The value walk writes the offset field of every region through
all-ones, all-zeros, an alternating pattern and five addends that carry across
each 9-bit chunk of the adder, with ``REGION_ATTRS.valid`` clear on every
region throughout -- the table inputs move and no beat is steered. The traffic
phase then makes the whole table valid at once, each region owning a 4 KiB
source page and translating it onto its own SEP SRAM page, and issues one read
and one write per region, plus one beat that lies outside every window for the
no-hit pass-through.

The source pages sit at 0x0800_0000, inside the external-chiplet range the SEP
crossbar routes to the local-master port the remapper sits on, and outside
every block this test addresses, so a valid region cannot capture the CPU-LSU
register path the test drives. The destinations are SRAM pages, which answer a
read and a write at any offset. The table is invalidated again at the end.

no_cpu, +skip_fuse_sense: the remapper does not depend on a fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import (
    ALIAS_REGIONS,
    PAGE_SIZE,
    SEP_SRAM_BASE,
    SepCovAliasRemap,
    cov_read_seq,
    cov_write_seq,
)

# One beat per region at a different offset inside its 4 KiB page, so the low
# address bits the remapper preserves move from region to region.
_INTRA_STEP = 0x40
# Past every mapped destination page (region 15 ends at SRAM + 16 x 4 KiB), and
# outside every source window, so this beat takes the no-hit pass-through.
_NO_HIT_ADDR = SEP_SRAM_BASE + ALIAS_REGIONS * PAGE_SIZE + 0x100


@pyuvm.test()
class sep_cov_alias_remap_region_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Walk the offset field of every region, then drive a beat through each.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        alias = SepCovAliasRemap(self)

        writes = await alias.offset_value_walk()
        self.logger.info("alias-remap offset walk: %d register writes, table invalid", writes)

        await alias.map_all_regions_to_sram()
        for region in range(ALIAS_REGIONS):
            intra = (region * _INTRA_STEP) & (PAGE_SIZE - 1)
            src = SepCovAliasRemap.src_page(region) + intra
            await self.start_seq(cov_write_seq(src, 0xA110_0000 | region))
            await self.start_seq(cov_read_seq(src))
        self.logger.info(
            "alias-remap traffic: one read and one write through %d regions", ALIAS_REGIONS
        )

        # Outside every window: the beat passes through unchanged.
        await self.start_seq(cov_write_seq(_NO_HIT_ADDR, 0x0B0B_0B0B))
        await self.start_seq(cov_read_seq(_NO_HIT_ADDR))

        await alias.invalidate_all()
