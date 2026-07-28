# SPDX-License-Identifier: Apache-2.0
"""I3C multi-controller CSR decode depth test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# The open-source I3C core is now integrated (git ca7d5fc91 "I3c core rebase
# #3934"), so these CSR windows decode to the real core and return real values
# (OKAY), not the old i3ccore_stub error signature. HCI_VERSION reads back the
# spec constant 0x120; HC_CAPABILITIES value is not spec-anchored here (OKAY
# decode only). OCA_I3C_WRAP CSR bases: WRAP_0=0xC003_A000, WRAP_1=0xC003_B000,
# WRAP_2=0xC003_C000 (stride 0x1000). Migrated from the pre-#d36a40bdb layout
# (0xC000_5000 stride 0x500), which is now an unmapped periph-xbar hole.
HCI_VERSION = 0x120

I3C_READS = [
    ("I3C0_HCI_VERSION", 0xC003_A000, HCI_VERSION),
    ("I3C0_HC_CAPABILITIES", 0xC003_A00C, None),
    ("I3C1_HCI_VERSION", 0xC003_B000, HCI_VERSION),
    ("I3C1_HC_CAPABILITIES", 0xC003_B00C, None),
    ("I3C2_HCI_VERSION", 0xC003_C000, HCI_VERSION),
    ("I3C2_HC_CAPABILITIES", 0xC003_C00C, None),
]


class smc_i3c_multi_controller_csr_test_seq(SmcCsrSeq):
    """Cover multiple I3C wrapper CSR windows before protocol BFM support."""

    def __init__(self, name: str = "smc_i3c_multi_controller_csr_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(I3C_READS)
        assert self.accesses == len(I3C_READS), "I3C multi-controller depth mismatch"
