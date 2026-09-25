# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FILTER_CONFIG field cycle and write-once lock on all 32 filter entries.

Drives every software-writable FILTER_CONFIG field of the 16 inbound and 16
outbound entries to all-ones and all-zeros through half-register writes, reads
each entry back against its generated RDL contract, restores the RDL reset, and
then sets and re-tests the write-once lock on every entry.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_filter_config_field_sweep_test_seq import smc_filter_config_field_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 32 filter entries, 18 SEP_IN AXI accesses each:
#   field cycle: reset read, 2x(half write + readback) for the ones pattern,
#     the same for the zeros pattern, 2 restore writes, restore read        12
#   lock leg: the set write and its readback, then two refused writes each
#     with a readback                                                        6
FILTER_CONFIG_FIELD_SWEEP_MIN_CSR_ACCESSES = 32 * 18


@pyuvm.test()
class smc_filter_config_field_sweep_test(smc_base_test):
    """Cycle every FILTER_CONFIG field and the write-once lock on all 32 entries."""

    required_evidence = (
        "CHK-FILTER-CONFIG-FIELD-SWEEP",
        "CHK-FILTER-CONFIG-LOCK-WOSET",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_config_field_sweep_test_seq("smc_filter_config_field_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            min_csr_accesses=FILTER_CONFIG_FIELD_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} FILTER_CONFIG field cycles and "
                f"{seq.locks_held} write-once locks"
            ),
        )
