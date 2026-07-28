# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: OCA_I3C_WRAP 3/4/5 CSR precheck (TC_SMC_P1CG_03).

RTL exposes 6 OCA_I3C_WRAP instances (0..5) at 0xC003_A000 stride 0x1000.
The P0/P1 slate covers 0/1/2 (`smc_i3c_multi_controller_csr_test`);
this test covers the remaining 3/4/5 with a HCI_VERSION read per instance.

The open-source I3C core is now integrated (git ca7d5fc91 "I3c core rebase
#3934"), so wrap 3/4/5 decode to the real core and read back the HCI_VERSION
spec constant 0x120 with an OKAY response (no longer the i3ccore_stub error
signature).
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

HCI_VERSION = 0x120

I3C_HCI_READS = [
    ("I3C_WRAP_3_HCI_VERSION", 0xC003_D000, HCI_VERSION),
    ("I3C_WRAP_4_HCI_VERSION", 0xC003_E000, HCI_VERSION),
    ("I3C_WRAP_5_HCI_VERSION", 0xC003_F000, HCI_VERSION),
]


class smc_i3c_wrap_extended_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        await self.csr_read_many(I3C_HCI_READS)
        assert self.accesses == len(I3C_HCI_READS), (
            "I3C wrap 3/4/5 HCI_VERSION precheck mismatch"
        )
