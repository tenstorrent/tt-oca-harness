# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS RAS-bank / NDM-reset / DFX-debug diagnostic CSR smoke.

No ECC and no DBS register is read by this testcase -- neither surface exists at
the SMC CSR boundary. The testcase name does not describe the surface; see
the sequence docstring for what is actually addressed.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_diagnostic_vip_utils import check_diagnostic_observability
from seq_lib.smc_ecc_dfd_dbs_sanity_test_seq import smc_ecc_dfd_dbs_sanity_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_ecc_dfd_dbs_sanity_test_seq, directed, no polling):
#   1 AXI-Lite master activity positive control (prove_axil_any_master_activity)
# + 3 value-compared diagnostic CSR reads (DIAGNOSTIC_READS)
# + 1 NDMRESET_CLUSTER_COUNT RDL-bounded read
# + 2 NDMRESET_CLUSTER_COUNT sw=r write + readback
# = 7. The floor counts the write/readback pair, so a regression that silently
# dropped it fails here rather than clearing a lower number.
ECC_DFD_DBS_MIN_CSR_ACCESSES = 7


@pyuvm.test()
class smc_ecc_dfd_dbs_sanity_test(smc_base_test):
    """Run the diagnostic representative CSR precheck."""

    required_evidence = (
        "CHK-DIAG-AXIL-ACTIVE",
        "CHK-DIAG-AXIL-IDLE",
        "CHK-DIAG-CSR-COUNT",
        "CHK-DIAG-CSR-DFX_DEBUG_BUS_MUX",
        "CHK-DIAG-CSR-DFX_DEBUG_CTRL",
        "CHK-DIAG-CSR-NDMRESET_PROCESS",
        "CHK-DIAG-NDMRESET-CLUSTER-COUNT-BOUNDS",
        "CHK-DIAG-NDMRESET-CLUSTER-COUNT-RO",
        "CHK-EFUSE-BANK-AXIL-ACTIVE",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ecc_dfd_dbs_sanity_test_seq("ecc_dfd_dbs_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_diagnostic_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.DIAGNOSTIC,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=ECC_DFD_DBS_MIN_CSR_ACCESSES,
            # No timeout statistic is published: this sequence
            # uses only csr_read/csr_write, which leave `allow_timeout` False, so
            # the driver raises on expiry and `SmcCsrSeq.timeouts` can only ever
            # be 0 on this path. Publishing that structural zero would advertise
            # a measurement nobody took.
            timeouts=None,
            proxy=True,
            details=(
                "CSR-only diagnostic surface actually addressed: RAS bank "
                "type/instance ID, NDM reset (PROCESS + CLUSTER_COUNT), DFX "
                "debug CTRL and the full 64-bit DEBUG_BUS_MUX. No ECC and no DBS "
                "register is read -- neither surface exists in smc_addr.h. No "
                "fault inject on this surface"
            ),
        )
