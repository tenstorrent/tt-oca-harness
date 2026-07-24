# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: MMODE_REMAP + CLA + full ALIAS_REMAP sweep
(TC_SMC_P1CG_16/17/18).

Bundles three previously-unreached fabric-side surfaces:

* SMC_MMODE_REMAP_0..7 (0xC001_3000+ stride 0x08) — machine-mode
  remap table entries.
* SMC_CLA_REG (0xC016_0000) — Cluster Local Aggregator registers.
* SMC_ALIAS_REMAP_0..7 (0xC001_2000+ stride 0x20) full sweep — P0/P1-4
  only touch entry 0.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq


class smc_remap_cla_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # MMODE_REMAP + ALIAS_REMAP are real fabric CSRs and decode/return OKAY
        # here: csr_read gates each on the scoreboard's resp_ok, so a broken remap
        # decode fails the test.
        # MMODE_REMAP 0..7 (stride 0x08, ATTRS-only per entry).
        for i in range(8):
            await self.csr_read(
                f"MMODE_REMAP_{i}_ATTRS", 0xC001_3000 + i * 0x08
            )
        # ALIAS_REMAP 0..7 (stride 0x20, START/END/ATTRS per entry).
        for i in range(8):
            base = 0xC001_2000 + i * 0x20
            await self.csr_read(f"ALIAS_REMAP_{i}_START", base + 0x00)
            await self.csr_read(f"ALIAS_REMAP_{i}_END",   base + 0x08)
            await self.csr_read(f"ALIAS_REMAP_{i}_ATTRS", base + 0x10)
        # SMC_CLA_REG is an error-slave window (SLVERR, data=0) in the OSS bench
        # (CLA is power-gated / absent). Assert the error response deterministically
        # -- fails if it ever starts returning OKAY.
        await self.csr_read_expect_error("CLA_CTRL",   0xC016_0000)
        await self.csr_read_expect_error("CLA_STATUS", 0xC016_0004)
        await self.csr_read_expect_error("CLA_INTR",   0xC016_0008)
        # 8 (MMODE) + 24 (ALIAS x 3 fields) + 3 (CLA) = 35
        assert self.accesses == 35, "MMODE + ALIAS + CLA sweep count mismatch"
