# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sweep AxPROT on WRITES into every sep_system_csr register bank.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the WRITE-side `aw.prot` lanes of the per-slot and per-region
register slices in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv` --
`gen_outbound_filter_reg[*].filter_reg_req.aw.prot`,
`gen_inbound_filter_reg[*].filter_reg_req.aw.prot`,
`local_master_aR_reqs[*].aw.prot`, `ap_output_remap_reqs[*].aw.prot` and
`stee_output_remap_reqs[*].aw.prot`. All three bits are untoggled on the
filter slices in the merged report.

`sep_cov_xbar_axprot_sweep_test` already sweeps AxPROT, but its write set is
two addresses -- CLOCK_GATE_CTRL and one alias-remap REGION_START -- so a
prot-swept write never reaches the filter demux legs or the AP and STEE remap
legs at all. Its reads do reach them: `ar.prot[1:0]` is live on those slices
while `aw.prot` is not. This leaf is the write half.

Stimulus: with AxPROT swept over 0b000..0b111, write the reset value into one
register word of each bank -- the first and last outbound filter slot, the
first and last inbound filter slot, the first and last alias-remap region, and
the first and last AP and STEE output-remap region. Every one of those words
resets to zero, so writing zero leaves the bank exactly as it was; the data
lane is not what this leaf drives.

FILTER_CONFIG is written at its low word only, where FILTER_CONFIG.locked[63]
does not live, so no slot is locked and `data_bus_width[14:12]` stays the RO
value the block drives. No filter or remap region is enabled anywhere in this
leaf, so no access it issues is filtered or remapped.

The SEP fabric does not decode on AxPROT, so a swept access is answered
exactly as the default one is.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import (
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    INFILT_ENTRIES,
    OUTFILT_BASE,
    OUTFILT_ENTRIES,
    SepCovStim,
)
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

PROT_VALUES = tuple(range(8))


def _bank_words() -> tuple[int, ...]:
    """One register word per addressed slot or region, at the bank ends.

    Every address here resets to zero, so the sweep writes zero and the bank
    keeps the state it had. The first and last index of each bank are used so
    the demux select lanes move as well as the prot lanes.
    """
    words: list[int] = []
    for base, count in ((OUTFILT_BASE, OUTFILT_ENTRIES), (INFILT_BASE, INFILT_ENTRIES)):
        for index in (0, count - 1):
            slot = base + index * FILTER_STRIDE
            words += [slot + FILTER_START_ADDR, slot + FILTER_END_ADDR, slot + FILTER_CONFIG]
    for index in (0, ALIAS_REGIONS - 1):
        region = ALIAS_BASE + index * ALIAS_STRIDE
        words += [region + ALIAS_START, region + ALIAS_END, region + ALIAS_ATTRS]
    for bank_base in (AP_BASE, STEE_BASE):
        for index in (0, REMAP_REGIONS - 1):
            words.append(bank_base + index * REMAP_STRIDE + REMAP_ATTRS)
    return tuple(words)


BANK_WORDS = _bank_words()


@pyuvm.test()
class sep_cov_csr_bank_prot_write_sweep_test(sep_base_test):
    """AxPROT 0b000..0b111 on writes into every CSR bank. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for prot in PROT_VALUES:
            for addr in BANK_WORDS:
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=addr,
                    wdata=0,
                    prot=prot,
                    name=f"cov_bankprot{prot}_wr",
                )
            self.logger.info(
                "AxPROT=0b%s driven on writes into %d CSR bank words", format(prot, "03b"), len(BANK_WORDS)
            )
