# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Read every remap region back while it holds a walked pattern.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the AXI-Lite READ RESPONSE path of the three remap banks in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv` --
`local_master_aR_resps[*].r.data`, `ap_output_remap_resps[*].r.data` and
`stee_output_remap_resps[*].r.data` -- together with the read-select lanes
`ap_output_remap_reqs[*].ar.addr[2:0]` and
`stee_output_remap_reqs[*].ar.addr[2:0]`, which the per-region blocks take as
their register offset (`sep_system_csr.sv:386`).

`sep_cov_csr_remap_region_data_walk_test` walks the same words, but
`SepCovStim.word_walk` (`seq_lib/sep_cov_stimulus_seq.py`) issues writes only,
so the three response buses carry a reset value for the whole run. This leaf
is the read half of that walk.

Stimulus: for each of the 16 local-master alias regions, write a pattern into
one 32-bit word of REGION_START, REGION_END or REGION_ATTRS and read that word
back; then the same over both words of REGION_ATTRS on each of the 16 AP and
16 STEE output-remap regions. Bank geometry comes from
`seq_lib/sep_fabric_csr_bank_seq.py`.

Ordering is the one the write-only walk uses: REGION_START and REGION_END
before REGION_ATTRS, and every walk ends on the all-zero pattern. So
REGION_ATTRS.cacheable[62] and REGION_ATTRS.valid[63] -- both plain R/W in
`hw/ip/axi_alias_remap/regs/alias_remap.rdl` -- move while that region's
window is empty and are left clear afterwards. No access in this leaf is
remapped, including the readbacks it issues.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import WALK_PATTERNS, SepCovStim
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
class sep_cov_csr_remap_region_readback_walk_test(sep_base_test):
    """Write-then-read pattern walk across every remap region word. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for region in range(ALIAS_REGIONS):
            base = ALIAS_BASE + region * ALIAS_STRIDE
            for offset in (ALIAS_START, ALIAS_END, ALIAS_ATTRS):
                await self._walk_and_read(stim, base + offset)
                await self._walk_and_read(stim, base + offset + 4)
        self.logger.info(
            "local-master alias remap write+read walk driven over %d regions", ALIAS_REGIONS
        )

        for name, bank_base in (("AP", AP_BASE), ("STEE", STEE_BASE)):
            for region in range(REMAP_REGIONS):
                base = bank_base + region * REMAP_STRIDE + REMAP_ATTRS
                await self._walk_and_read(stim, base)
                await self._walk_and_read(stim, base + 4)
            self.logger.info(
                "%s output-remap write+read walk driven over %d regions", name, REMAP_REGIONS
            )

    async def _walk_and_read(self, stim: SepCovStim, addr: int) -> None:
        """Write each pattern to one CSR word and read the word back.

        The read value is logged and dropped; nothing here expects a value.
        """
        for pattern in WALK_PATTERNS:
            await stim._wr(addr, pattern)
            await stim._rd(addr)
