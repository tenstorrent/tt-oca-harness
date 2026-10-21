# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_007 ANCHOR: smc_axil_endpoint_prot_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: dc47a2b61b4edb0599729c5ce139a1ec08ebd24ae4262a16e3f82a5fb86c790c
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 3 ENV: cocotb
"""AxPROT, AxUSER, AxREGION, AxQOS, AxLOCK, AxCACHE, AxLEN and AxID at every AXI-Lite endpoint.

From SEP_IN, one register of every internal AXI-Lite endpoint takes a read and
a write-back of the value it holds under each value of each request attribute,
and the debug manager (JTAG AXI) reads the reset unit with AxPROT 0x3 and 0x0.
Every compared read returns the zero-attribute reference and every write-back
leaves the register unchanged.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_axil_endpoint_prot_sweep_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_axil_endpoint_prot_sweep_test_seq import smc_axil_endpoint_prot_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from the
# sequence: 59 endpoints, each with a reference read; per attribute value a
# read, a write-back and a zero-attribute read, over 8 AxPROT, 14 AxUSER,
# 6 AxREGION, 6 AxQOS, 2 AxLOCK, 10 AxCACHE, 1 AxLEN and 5 AxID values, plus
# the closing AxPROT read; 8 classes x 4 outstanding reads; the burst set's
# footprint reads (34 before, 34 after), burst reads and writes (2 x 8); and
# the five mailbox clock-gate accesses; and per seeded endpoint (52) a pre-seed
# read, the seed write and the restoring write and read.
ENDPOINTS = 59
SEEDED_ENDPOINTS = 52
ATTRIBUTE_VALUES = 8 + 14 + 6 + 6 + 2 + 10 + 1 + 5
PROT_SWEEP_MIN_CSR_ACCESSES = (
    ENDPOINTS * (1 + 3 * ATTRIBUTE_VALUES + 1) + 8 * 4 + 2 * 34 + 2 * 8 + 5 + 4 * SEEDED_ENDPOINTS
)
DEBUG_MANAGER_ACCESSES = 2


@pyuvm.test()
class smc_axil_endpoint_prot_sweep_test(smc_base_test):
    """Every request attribute, non-zero then zero, at every AXI-Lite endpoint."""

    required_evidence = (
        "CHK-ATTR-CACHE",
        "CHK-ATTR-DEBUG-MANAGER",
        "CHK-ATTR-ID",
        "CHK-ATTR-ID-OUTSTANDING",
        "CHK-ATTR-LEN",
        "CHK-ATTR-LOCK",
        "CHK-ATTR-PROT",
        "CHK-ATTR-QOS",
        "CHK-ATTR-REGION",
        "CHK-ATTR-USER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axil_endpoint_prot_sweep_test_seq("smc_axil_endpoint_prot_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.endpoints) == ENDPOINTS, (
            f"the check set holds {len(seq.endpoints)} endpoints, expected {ENDPOINTS}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=PROT_SWEEP_MIN_CSR_ACCESSES,
            proxy=False,
            fabric_bus="JTAG AXI",
            fabric_accesses=DEBUG_MANAGER_ACCESSES,
            min_fabric_accesses=DEBUG_MANAGER_ACCESSES,
            fabric_access_label="JTAG AXI debug-manager read",
            details=(
                f"{len(seq.endpoints)} endpoints x {ATTRIBUTE_VALUES} attribute "
                f"values, {seq.waits} bounded waits"
            ),
        )
