# SPDX-License-Identifier: Apache-2.0
"""I3C recovery/status CSR proxy test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# The open-source I3C core is now integrated (git ca7d5fc91 "I3c core rebase
# #3934"): these status CSRs decode to the real core and return real values with
# an OKAY response (no longer the i3ccore_stub error signature). Values are not
# spec-anchored here, so each read is gated on OKAY decode/route + no-hang.
# OCA_I3C_WRAP_0 CSR base = 0xC003_A000 (migrated from 0xC000_5000; per-register
# offsets unchanged). The old 0xC000_50xx window is now an unmapped hole.
I3C_STATUS_READS = [
    ("I3C0_PRESENT_STATE", 0xC003_A014, None),
    ("I3C0_INTR_STATUS", 0xC003_A020, None),
    ("I3C0_DAT_SECTION_OFFSET", 0xC003_A030, None),
    ("I3C0_DCT_SECTION_OFFSET", 0xC003_A034, None),
    ("I3C0_IBI_NOTIFY_CTRL", 0xC003_A058, None),
    ("I3C0_IBI_DATA_ABORT_CTRL", 0xC003_A05C, None),
]


class smc_i3c_recovery_status_csr_test_seq(SmcCsrSeq):
    """Sample recovery, table-offset, and IBI-related CSR status fields."""

    def __init__(self, name: str = "smc_i3c_recovery_status_csr_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(I3C_STATUS_READS)
        assert self.accesses == len(I3C_STATUS_READS), "I3C status CSR depth mismatch"
