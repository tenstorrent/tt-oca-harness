# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_XVISOR_REMAP full sweep (TC_SMC_P1CG_20).

RTL exposes an 8-entry hypervisor remap table (PeakRDL map
SMC_XVISOR_REMAP_0..7, ATTRS-only per entry), a sibling of the ALIAS_REMAP and
MMODE_REMAP tables. Strict reads (each requiring an OKAY AXI response) prove
per-entry CSR decode + reset invariants without any BFM/firmware.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
)

# Per-entry REGION_ATTRS addresses from the generated map. Reset is 0 per
# output_remap.rdl (offset[55:0]=0x0, remap disabled) — RDL-traceable.
XVISOR_REMAP_ATTRS_ADDRS = (
    SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
)


class smc_xvisor_remap_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # XVISOR_REMAP 0..7 (ATTRS-only per entry). Asserting reset=0 verifies
        # per-entry decode AND the spec-defined reset content, not merely OKAY.
        observed = []
        for i, addr in enumerate(XVISOR_REMAP_ATTRS_ADDRS):
            observed.append(
                await self.csr_read(
                    f"XVISOR_REMAP_{i}_ATTRS",
                    addr,
                    expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                )
            )
        assert self.accesses == len(XVISOR_REMAP_ATTRS_ADDRS), "XVISOR_REMAP sweep count mismatch"
        cocotb.log.info(
            "CHK-XVISOR-REMAP-RESET-DEFAULT: XVISOR_REMAP_0..%d REGION_ATTRS at "
            "%#x..%#x read %s over SEP_IN AXI, each an OKAY scoreboard value "
            "compare against the RDL reset %#x",
            len(XVISOR_REMAP_ATTRS_ADDRS) - 1,
            XVISOR_REMAP_ATTRS_ADDRS[0],
            XVISOR_REMAP_ATTRS_ADDRS[-1],
            [f"{value:#x}" for value in observed],
            OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
        )
