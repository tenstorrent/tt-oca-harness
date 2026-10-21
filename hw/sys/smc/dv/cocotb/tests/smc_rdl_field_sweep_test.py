# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_009 ANCHOR: smc_rdl_field_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 9843278d346aa785a345c4b6004a82cec7c2f7903d43ba2e131be90be0c68200
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B4_VPLAN_DETAIL_2.md @ artifact_revision 1 ENV: cocotb
"""RDL-contract sweep of the software-owned SMC CSR blocks over SEP_IN AXI.

Drives every register of SCRATCH_COLD, SCRATCH_COLD_WARM, DFX_CTRL,
SMC_BASE_CONFIG, CPU_CTRL and the two RESET_UNIT registers no other leaf drives
through the cycle its RDL software-access type allows, and restores each one to
its RDL reset. The adopter strap capture registers in the external window get
the `sw = r` half of the same treatment. The CHIP_CONFIG and NDM_RESET registers
take all-ones and single-lane writes, and ISOLATE_REQ_SMC_REG a zero-strobe
write.
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
#   REFERENCE_COUNTER: running sample + load + the first readback that shows
#     it + one more after that; a load that takes longer to cross adds reads  4
#   STRAPS_LO / STRAPS_HI: capture read + write + readback                     6
#   CHIP_CONFIG all-ones: 4 x (pre read + write + readback)                   12
#   CHIP_CONFIG single lanes: 16 x (write + readback)                         32
#   NDMRESET_PROCESS all-ones: pre read + 2 x (write + readback)               5
#   NDMRESET_PROCESS lanes: 4 x (write + readback) + restore + readback       10
#   NDMRESET_REQUEST / CLUSTER_COUNT: 2 x (pre read + 5 x (write + readback)) 22
#   ISOLATE_REQ_SMC_REG zero strobe: pre read + write + readback               3
#                                                                         ------
#                                                                            605
RDL_FIELD_SWEEP_MIN_CSR_ACCESSES = 605


@pyuvm.test()
class smc_rdl_field_sweep_test(smc_base_test):
    """Sweep every software-owned SMC CSR field against its RDL contract."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-RDL-CHIPCFG-ALLONES",
        "CHK-RDL-CHIPCFG-LANES",
        "CHK-RDL-ISO-ZERO-STROBE",
        "CHK-RDL-NDM-ALLONES",
        "CHK-RDL-NDM-LANES",
        "CHK-RDL-NDM-RO",
        "CHK-RDL-STRAPS-RO",
        "CHK-RDL-SWEEP-CYCLE",
        "CHK-RDL-SWEEP-SPECIAL",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_rdl_field_sweep_test_seq("rdl_field_sweep_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.fence) == 7, "the ordered fence did not record every term"
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
