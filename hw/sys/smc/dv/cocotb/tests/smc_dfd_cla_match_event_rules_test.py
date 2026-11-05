# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Grade the CLA match-event sense, the dead time match, the idle mux selects and the GPIO action.

On a debug bus measured in two states, each positive match code sets node 0
pair 1 only in the state its mask and match describe, with the match taken from
either state in turn, and its negative code only in the other; `Muxselseg4` to `Muxselseg7` of `DEBUG_BUS_MUX` and of
`CDbgMuxSelLo` leave the snapshot where it is while `Muxselseg0` moves it; the
`EventType0` sweep sees the same live indices whatever `CDbgClaTimeMatch`
holds; and the full `Action0` sweep moves no GPIO pad output or enable bit that
was not already moving on its own, while it raises `tb_cla_interrupt`.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_cla_match_event_rules_test_seq import (
    smc_dfd_cla_match_event_rules_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every discovery loop and poll
# is counted at one iteration, the shortest each can finish in.
#
#   DEBUG_CTRL force write, the CLA arm, one relation try (write, status read)  4
#   64 CLA mux writes                                                        64
#   sampled-mux discovery: 64 identifier-mode writes, the two-word
#     snapshot, one probe (write and two-word snapshot)                      69
#   match sense: 4 code pairs x (mask write + readback, then 2 match states
#     x (match write + readback, 2 codes x 4 relations x (2 bus states x
#     (mux write, pair write, 2 status writes, status read), pair quiesce,
#     2 status writes)))                                                    856
#   idle selects: mux write and two-word snapshot, then per register
#     (4 fields x (64 x (write and two-word snapshot) and the restore),
#     one control try (write and snapshot), the restore write and snapshot) 1559
#   GPIO action: the base write, 64 pair writes and the quiesce              66
#   time match: mux write, 3 values x (write + readback, 64 x (pair write,
#     2 status writes, status read, quiesce, 2 status writes), timestamp
#     read), the final write + readback                                    1356
#   restore: 2 pairs, 8 mask/match registers, CLA control, CLA mux,
#     DEBUG_BUS_MUX, DEBUG_CTRL                                              14
#                                                                         ------
#                                                                          3988
MATCH_EVENT_RULES_MIN_CSR_ACCESSES = 3988


@pyuvm.test()
class smc_dfd_cla_match_event_rules_test(smc_base_test):
    """Match-event sense, idle mux selects, the dead time match and the GPIO action."""

    required_evidence = (
        "CHK-CLA-GPIO-ACTION-NO-PAD",
        "CHK-CLA-MATCH-NEGATE",
        "CHK-CLA-TIME-MATCH-DEAD",
        "CHK-DFX-MUXSEL47-NO-EFFECT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_match_event_rules_test_seq("cla_match_event_rules_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=MATCH_EVENT_RULES_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"mux {seq.sampled_mux}, states {[hex(v) for v in seq.states]}, relations "
                f"{seq.match_relations}, {seq.idle_samples} idle-select samples, controls "
                f"{seq.controls}, live sets {seq.live_sets}, {seq.pad_samples} pad samples, "
                f"baseline-moving pads {seq.pads_baseline}, sweep-moving pads {seq.pads_sweep}, "
                f"{seq.value_checks} value checks"
            ),
        )
