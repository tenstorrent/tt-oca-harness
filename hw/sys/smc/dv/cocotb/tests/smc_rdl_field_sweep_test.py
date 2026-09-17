# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RDL-contract sweep of the software-owned SMC CSR blocks over SEP_IN AXI.

Drives every register of SCRATCH_COLD, SCRATCH_COLD_WARM, DFX_CTRL,
SMC_BASE_CONFIG, CPU_CTRL and the two RESET_UNIT registers no other leaf drives
through the cycle its RDL software-access type allows, and restores each one to
its RDL reset. The adopter strap capture registers in the external window get
the `sw = r` half of the same treatment.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_rdl_field_sweep_test_seq import smc_rdl_field_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# Composition (no polling, every leg directed). The sweep list is 30 register
# paths expanding to 93 register instances:
#   7 read-only paths, one reset read per element: STATUS_SMU, SMC_ATTRIBUTES
#     and TEST_CTRL 1 each, WB_PC_CORE0..3 8 each = 35 instances              35
#   18 writable single registers, 12 accesses each: reset read, 2x(half write
#     + readback) for the ones pattern, the same for the low pattern,
#     2 restore writes and a restore read                                    216
#   5 writable arrays (SCRATCH_COLD 8, SCRATCH_COLD_WARM 8, CPU_CTRL SCRATCH
#     16, RESET_VECTOR 4, DUMMY_ROM_NULL 4 = 40 elements): the same 12 on
#     element 0, then 4 per element for the co-resident signature pass       220
#   WDT_TIMEOUT_RESET singlepulse: 2 writes + 2 readbacks                      4
#   MUTEX[0..3]: acquire + held + release + reacquire                         16
#   SEMA[0..3]: start + inc + readback + dec + readback                       20
#   REFERENCE_COUNTER: running sample + load + two samples after it            4
#   STRAPS_LO / STRAPS_HI: capture read + write + readback                     6
#                                                                         ------
#                                                                            521
RDL_FIELD_SWEEP_MIN_CSR_ACCESSES = 521


@pyuvm.test()
class smc_rdl_field_sweep_test(smc_base_test):
    """Sweep every software-owned SMC CSR field against its RDL contract."""

    required_evidence = (
        "CHK-RDL-STRAPS-RO",
        "CHK-RDL-SWEEP-CYCLE",
        "CHK-RDL-SWEEP-SPECIAL",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_rdl_field_sweep_test_seq("rdl_field_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=RDL_FIELD_SWEEP_MIN_CSR_ACCESSES,
            proxy=False,
            details=(
                f"{seq.registers_swept} register instances swept against the generated "
                f"RDL map, {seq.value_checks} value compares"
            ),
        )
