# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: every AP and STEE output-remap region offset.

``output_remap`` holds a sixteen-entry table per aperture and rewrites a beat
to ``{offset[55:IdxStart], adjusted_addr[IdxStart-1:0]}``. The suite programs
one AP region and leaves the second at offset 0, so ``remap_table[].offset``
never leaves reset on any region of either table and the region index carries
three of its values.

Two phases. The value walk writes the offset of all sixteen AP and all sixteen
STEE regions through all-ones, all-zeros, an alternating pattern and a
per-region value, with no beat issued into either aperture, so the table
inputs move and nothing is steered. The traffic phase then points one region at
a time at the outbound target aperture and issues one read and one write into
that region's own sub-window, so the index slice of the adjusted address steps
over the table and the preserved low bits change per beat.

One outbound-filter entry is opened over the whole target aperture before any
beat is issued, and every other outbound entry is disabled: the outbound filter
blocks by default, so the traffic needs exactly that one window and no other
rule is left live.

no_cpu, +skip_fuse_sense: the output-remap tables and the outbound path are
reachable from the CPU-LSU master without a real fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import (
    AP_REGIONS,
    OUTBOUND_TARGET_BASE,
    STEE_REGIONS,
    SepCovOutboundGate,
    SepCovOutputRemap,
    cov_read_seq,
    cov_write_seq,
)

# Per-region beat offset inside the region. Region 15 lands at 0x3C8, well
# inside the target window the outbound filter entry grants.
_INTRA_STEP = 0x40
_INTRA_BASE = 0x8


@pyuvm.test()
class sep_cov_output_remap_region_offset_sweep_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Walk both tables' offsets, then drive a beat through every region.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        gate = SepCovOutboundGate(self)
        remap = SepCovOutputRemap(self)

        ap_writes = await remap.offset_value_walk(ap=True)
        stee_writes = await remap.offset_value_walk(ap=False)
        self.logger.info(
            "output-remap offset walk: %d AP writes, %d STEE writes", ap_writes, stee_writes
        )

        await gate.open_target_window()

        for ap, count in ((True, AP_REGIONS), (False, STEE_REGIONS)):
            bank = "AP" if ap else "STEE"
            for region in range(count):
                intra = _INTRA_BASE + region * _INTRA_STEP
                await remap.set_offset(ap=ap, region=region, offset=OUTBOUND_TARGET_BASE)
                access = SepCovOutputRemap.access_addr(ap=ap, region=region, intra=intra)
                await self.start_seq(cov_write_seq(access, 0x0BAD_0000 | region))
                await self.start_seq(cov_read_seq(access))
            self.logger.info("%s aperture: one read and one write through %d regions", bank, count)

        # Leave the outbound bank inert for whatever runs after this scenario.
        await gate.disable_all(inbound=False)
