# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An alias-remap region marked valid, and its attributes held across a write.

Checks all eight regions read with valid clear, marks the last one cacheable
and valid over a window its own reset leaves empty with the remap offset at
zero, writes the half of REGION_ATTRS the attribute bits do not occupy, and
requires both to survive it before restoring the register to its reset.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_alias_remap_region_attrs_test_seq import (
    smc_alias_remap_region_attrs_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   8 region attribute reads                                                  8
#   the window start and end reads                                            2
#   the two four-byte writes with both bits at reset, each with its read      4
#   the attribute write and its guard read                                    2
#   the low-half write and the read that shows both bits held                 2
#   the restore write and its read back                                       2
ALIAS_REMAP_REGION_ATTRS_MIN_CSR_ACCESSES = 20


@pyuvm.test()
class smc_alias_remap_region_attrs_test(smc_base_test):
    """Mark one empty alias-remap region valid and hold its attributes."""

    required_evidence = ("CHK-ALIAS-REMAP-ATTRS-RETAIN",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_alias_remap_region_attrs_test_seq("smc_alias_remap_region_attrs_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            min_csr_accesses=ALIAS_REMAP_REGION_ATTRS_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.regions_checked} regions checked idle, {seq.attrs_held} attribute "
                f"bits held across a partial write"
            ),
        )
