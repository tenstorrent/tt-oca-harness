# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound filter entries programmed with a region spanning two granules.

On outbound entries 1 to 15: program a region whose start and end sit in
different 4 KiB granules and require both address registers to read back
exactly as programmed, then a region inside one granule and require the
rounded pair filter_ctrl.rdl says hardware writes back. On entry 1, enable the
spanning region with write_allowed clear and copy through it with the DMA: the
copy inside must leave its destination at the sentinel it was seeded with, the
copy a granule above must land.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_region_span_test_seq import smc_filter_region_span_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. CSR accesses only; the JTAG
# traffic of the enforcement leg goes through its own agent.
#
#   the entry-0 quiet check                                                   1
#   15 entries x (the allow_burst write, two region programmings of two
#     writes and two readbacks each, and three restore writes)           15 x 12
#   the traffic leg: the region writes and readbacks, the config write and
#     its readback, and two DMA descriptors of 14 CSR accesses each        37
#   the three restore writes of the traffic entry and their readbacks       6
FILTER_REGION_SPAN_MIN_CSR_ACCESSES = 1 + 15 * 12 + 37 + 6


@pyuvm.test()
class smc_filter_region_span_test(smc_base_test):
    """Program a two-granule filter region on every entry, and drive one."""

    required_evidence = (
        "CHK-FILTER-REGION-ENFORCED",
        "CHK-FILTER-REGION-SPAN",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_region_span_test_seq("smc_filter_region_span_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            min_csr_accesses=FILTER_REGION_SPAN_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.spanning} spanning and {seq.rounded} rounded readbacks, "
                f"{seq.denied} refused and {seq.allowed} permitted writes"
            ),
        )
