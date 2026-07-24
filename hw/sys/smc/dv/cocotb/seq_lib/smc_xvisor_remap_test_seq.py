# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap Round 4: SMC_XVISOR_REMAP full sweep (TC_SMC_P1CG_20).

RTL exposes an 8-entry hypervisor remap table at 0xC001_4000 (stride
0x08, one REGION_ATTRS register per entry). This is a direct sibling of
the already-covered ALIAS_REMAP (0xC001_2000) and MMODE_REMAP
(0xC001_3000) tables, but no prior P0/P1 test reached it. Strict reads (each requiring
an OKAY AXI response) prove per-entry CSR decode + reset invariants
without any BFM/firmware.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

XVISOR_REMAP_BASE = 0xC001_4000
XVISOR_REMAP_STRIDE = 0x08
XVISOR_REMAP_ENTRIES = 8


class smc_xvisor_remap_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # XVISOR_REMAP 0..7 (stride 0x08, ATTRS-only per entry). Each entry's
        # REGION_ATTRS resets to 0 per output_remap.rdl (offset[55:0]=0x0, remap
        # disabled) -> RDL-traceable, G3 spec-anchored. Asserting it verifies
        # per-entry decode AND the spec-defined reset content, not merely OKAY.
        for i in range(XVISOR_REMAP_ENTRIES):
            await self.csr_read(
                f"XVISOR_REMAP_{i}_ATTRS",
                XVISOR_REMAP_BASE + i * XVISOR_REMAP_STRIDE,
                expected=0x0,
            )
        assert self.accesses == XVISOR_REMAP_ENTRIES, "XVISOR_REMAP sweep count mismatch"
