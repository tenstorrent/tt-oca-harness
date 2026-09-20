# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: the alias-remap cacheable attribute on a live beat.

``axi_alias_remap`` drives ``axi_out_req_o.aw.cache`` and ``.ar.cache`` from
``REGION_ATTRS.cacheable`` on a hit, and passes the incoming ``AxCACHE``
through on a miss. No test in the suite ever sets the attribute, so
``aw_remapped_cacheable`` and ``ar_remapped_cacheable`` hold one value for the
whole simulation.

One region is mapped from an unissued source page onto a SEP SRAM page. A read
and a write cross it with ``cacheable`` set, then the attribute is rewritten
clear and the same pair repeats. A third pair goes to an address outside every
window, where the incoming attribute passes through.

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

_REGION = 0
_INTRA = 0x80
_NO_HIT_ADDR = SEP_SRAM_BASE + ALIAS_REGIONS * PAGE_SIZE + 0x200


@pyuvm.test()
class sep_cov_alias_remap_cacheable_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Drive one region with cacheable set, then clear, then a no-hit beat.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        alias = SepCovAliasRemap(self)
        await alias.invalidate_all()

        src_page = SepCovAliasRemap.src_page(_REGION)
        dst_page = SepCovAliasRemap.dst_page(_REGION)
        offset = SepCovAliasRemap.offset_for(src_page, dst_page)
        access = src_page + _INTRA

        for cacheable in (True, False):
            await alias.program(
                _REGION,
                start=src_page,
                end=src_page + PAGE_SIZE,
                offset=offset,
                valid=True,
                cacheable=cacheable,
            )
            await self.start_seq(cov_write_seq(access, 0xCAC0_0000 | int(cacheable)))
            await self.start_seq(cov_read_seq(access))
            self.logger.info(
                "alias-remap region %d driven with cacheable=%d", _REGION, int(cacheable)
            )

        # Outside every window: the incoming AxCACHE passes through.
        await self.start_seq(cov_write_seq(_NO_HIT_ADDR, 0x0C0C_0C0C))
        await self.start_seq(cov_read_seq(_NO_HIT_ADDR))

        await alias.invalidate_all()
