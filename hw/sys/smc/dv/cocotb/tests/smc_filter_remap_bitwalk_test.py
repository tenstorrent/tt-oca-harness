# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A one and a zero walked across every filter, remap and mailbox-strobe bit.

Every bit of START_ADDR and END_ADDR on all 32 filter entries and of
REGION_START and REGION_END on all 8 alias-remap regions takes a one and a
zero with the register read back after each write, and every mailbox aperture
takes strobed WRITE_DATA writes whose paired READ_DATA must return the strobed
bytes and nothing else.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_remap_bitwalk_test_seq import smc_filter_remap_bitwalk_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   32 filter entries: a FILTER_CONFIG guard read                               32
#     56 bits x 2 patterns x (START write, END write, two readbacks)         14336
#     restore: 2 writes + 2 readbacks                                           128
#   8 remap regions: a REGION_ATTRS guard read                                    8
#     44 bits x 2 patterns x (START write, END write, two readbacks)          2816
#     restore: 2 writes + 2 readbacks                                            32
#   64 mailbox apertures: 8 walking-one strobes + 4 shared patterns, each a
#     strobed write and a paired readback, less the empty pattern            1534
#     ERROR_FLAGS read, IRQS acknowledge and readback                           192
FILTER_REMAP_BITWALK_MIN_CSR_ACCESSES = 32 + 14336 + 128 + 8 + 2816 + 32 + 1534 + 192


@pyuvm.test()
class smc_filter_remap_bitwalk_test(smc_base_test):
    """Walk every filter, remap and mailbox-strobe bit, reading each one back."""

    required_evidence = (
        "CHK-FILTER-ADDR-BITWALK",
        "CHK-MAILBOX-STROBE-WALK",
        "CHK-REMAP-REGION-BITWALK",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_remap_bitwalk_test_seq("smc_filter_remap_bitwalk_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=FILTER_REMAP_BITWALK_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.filter_entries} filter entries x {seq.filter_bits // (2 * seq.filter_entries)} "
                f"bits, {seq.remap_regions} remap regions x "
                f"{seq.remap_bits // seq.remap_regions} bits, {seq.strobe_writes} strobed "
                f"mailbox writes over {seq.mailbox_apertures} apertures, "
                f"{seq.value_checks} value compares"
            ),
        )
