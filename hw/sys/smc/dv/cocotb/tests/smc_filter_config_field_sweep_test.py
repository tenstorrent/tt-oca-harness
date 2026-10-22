# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_002 ANCHOR: smc_filter_config_field_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 17fb66a68ae906cb9def81735ba1b37a8b7a111eeb7a9f96a37086793dcd9682
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 199 `smc_filter_config_field_sweep_test` ENV: cocotb
"""FILTER_CONFIG field cycle, write-once lock and its cold-reset clear on all 32 filter entries.

Drives every software-writable FILTER_CONFIG field of the 16 inbound and 16
outbound entries to all-ones and all-zeros through half-register writes, reads
each entry back against its generated RDL contract, restores the RDL reset,
then sets and re-tests the write-once lock on every entry. One cold reset from
the bench reset agent follows; every entry then reads its documented reset
words with the lock clear and accepts an `allow_ns` write again.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib._one_shot import _OneShot
from seq_lib.smc_filter_config_field_sweep_test_seq import smc_filter_config_field_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 32 filter entries, 25 SEP_IN AXI accesses each:
#   field cycle: reset read, 2x(half write + readback) for the ones pattern,
#     the same for the zeros pattern, 2 restore writes, restore read        12
#   lock leg: the set write and its readback, then two refused writes each
#     with a readback                                                        6
#   after the cold reset: FILTER_CONFIG, START_ADDR and END_ADDR reads, the
#     allow_ns write and its readback, the restore write and its readback    7
FILTER_CONFIG_FIELD_SWEEP_MIN_CSR_ACCESSES = 32 * 25


@pyuvm.test()
class smc_filter_config_field_sweep_test(smc_base_test):
    """Cycle every FILTER_CONFIG field and the write-once lock, then clear it by cold reset."""

    required_evidence = (
        "CHK-FILTER-COLD-RESET-UNLOCK",
        "CHK-FILTER-COLD-RESET-WORDS",
        "CHK-FILTER-COLD-RESET-WRITABLE",
        "CHK-FILTER-CONFIG-FIELD-SWEEP",
        "CHK-FILTER-CONFIG-LOCK-WOSET",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_config_field_sweep_test_seq("smc_filter_config_field_sweep_test_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            min_csr_accesses=FILTER_CONFIG_FIELD_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} FILTER_CONFIG field cycles and "
                f"{seq.locks_held} write-once locks, cleared by one cold reset"
            ),
        )
