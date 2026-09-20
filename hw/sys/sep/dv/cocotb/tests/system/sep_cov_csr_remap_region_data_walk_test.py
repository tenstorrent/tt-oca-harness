# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Data walk over every alias-remap, AP output-remap and STEE output-remap region.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `local_masters_alias_remap_reg_ctrl_o`,
`ap_output_remap_reg_ctrl_o` and `stee_output_remap_reg_ctrl_o` in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv`. The two
output-remap control structs are at zero toggle: the existing bank sweep
writes one masked-random value into one AP and one STEE region per seed.

Stimulus: for each of the 16 local-master alias regions drive
0xFFFF_FFFF, 0x5555_5555, 0xAAAA_AAAA and 0x0000_0000 through both 32-bit
words of REGION_START, REGION_END and REGION_ATTRS, then the same walk through
both words of REGION_ATTRS on each of the 16 AP and 16 STEE output-remap
regions. Bank geometry comes from `seq_lib/sep_fabric_csr_bank_seq.py`.

Per region the walk drives REGION_START and REGION_END before REGION_ATTRS and
each walk ends on the all-zero pattern, so REGION_ATTRS.cacheable[62] and
REGION_ATTRS.valid[63] -- both plain R/W in
`hw/ip/axi_alias_remap/regs/alias_remap.rdl` -- are moved while that region's
window is empty, and are left clear afterwards. No access in this leaf is
therefore remapped.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_REGIONS,
    ALIAS_START,
    ALIAS_STRIDE,
    AP_BASE,
    REMAP_ATTRS,
    REMAP_REGIONS,
    REMAP_STRIDE,
    STEE_BASE,
)


@pyuvm.test()
class sep_cov_csr_remap_region_data_walk_test(sep_base_test):
    """Pattern walk across every remap region control word. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for region in range(ALIAS_REGIONS):
            base = ALIAS_BASE + region * ALIAS_STRIDE
            for offset in (ALIAS_START, ALIAS_END, ALIAS_ATTRS):
                await stim.word_walk(base + offset)
                await stim.word_walk(base + offset + 4)
        self.logger.info("local-master alias remap walk driven over %d regions", ALIAS_REGIONS)

        for name, bank_base in (("AP", AP_BASE), ("STEE", STEE_BASE)):
            for region in range(REMAP_REGIONS):
                base = bank_base + region * REMAP_STRIDE + REMAP_ATTRS
                await stim.word_walk(base)
                await stim.word_walk(base + 4)
            self.logger.info("%s output-remap walk driven over %d regions", name, REMAP_REGIONS)
