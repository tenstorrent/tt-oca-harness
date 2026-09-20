# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sweep AxPROT over the filter, remap and CSR apertures.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the `aw.prot` / `ar.prot` fields carried on
`gen_outbound_filter_reg[*].filter_reg_req`, `local_master_aR_reqs[*]`,
`ap_output_remap_reqs[*]`, `stee_output_remap_reqs[*]` and `xbar_mst_req[*]`.
Every SEP access so far leaves AxPROT at the VIP default 0b000, so AxPROT[0]
(privileged) and AxPROT[2] (instruction) never move.

Stimulus: repeat a short read and write set over the outbound and inbound
filter banks, the local-master alias-remap bank, the AP and STEE output-remap
banks and SEP_CPU_CTRL, with `prot` swept over 0b000..0b111. The VIP already
accepts a `prot` argument; `seq_lib/sep_axi_access_seq.py` passes it through to
`SepAxiItem.prot`, which `env/sep_axi_agent.py` hands to the driver. This is
stimulus plumbing, not a force.

The writes are chosen so the sweep changes no state that a later step depends
on: CLOCK_GATE_CTRL takes the same implemented mask every fabric driver in
this tree writes, and the last alias region's REGION_START takes its reset
value of zero. The SEP fabric does not decode on AxPROT, so a swept access is
answered exactly as the default one is.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE, SepCovStim
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    ALIAS_REGIONS,
    ALIAS_START,
    ALIAS_STRIDE,
    AP_BASE,
    INFILT_BASE,
    OUTFILT_BASE,
    STEE_BASE,
)

READ_ADDRS = (
    OUTFILT_BASE,
    INFILT_BASE,
    ALIAS_BASE,
    AP_BASE,
    STEE_BASE,
    CLOCK_GATE_CTRL,
)

# (address, data) pairs whose write leaves the register at the value it
# already holds.
WRITE_ADDRS = (
    (CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE),
    (ALIAS_BASE + (ALIAS_REGIONS - 1) * ALIAS_STRIDE + ALIAS_START, 0),
)

PROT_VALUES = tuple(range(8))


@pyuvm.test()
class sep_cov_xbar_axprot_sweep_test(sep_base_test):
    """AxPROT 0b000..0b111 on the fabric apertures. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for prot in PROT_VALUES:
            for addr in READ_ADDRS:
                await stim.access(
                    op=SepAxiOp.READ,
                    addr=addr,
                    prot=prot,
                    name=f"cov_prot{prot}_rd",
                )
            for addr, data in WRITE_ADDRS:
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=addr,
                    wdata=data,
                    prot=prot,
                    name=f"cov_prot{prot}_wr",
                )
            self.logger.info("AxPROT=0b%03b driven over the fabric apertures", prot)
