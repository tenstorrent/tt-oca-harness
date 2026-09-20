# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sweep AxID over the whole CPU-LSU ID field on the fabric apertures.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "AXI fabric"): `aw.id` / `ar.id` on
`xbar_slv_req[*]` and `xbar_mst_req[*]` of
`hw/sys/sep/rtl/sep_local_axi_xbar.sv` and
`hw/sys/sep/rtl/crossbars/sep_system_peripherals_xbar.sv`, on
`sep_crypto_axi_reqs[*]` of `hw/sys/sep/rtl/sep_crypto_axi_interconnect.sv`,
and the `b.id` / `r.id` lanes the crossbars reflect back.

`SepAxiItem.axi_id` defaults to 0 and the note on it
(`cocotb/env/sep_axi_agent.py`) says so: the transaction ID is a dimension a
test opts into. Almost none do, so the crossbar master ports show only the
prepended slave-port index moving and the low ID bits held at zero --
`xbar_mst_req[0].aw.id[5:0]` is entirely untoggled and
`xbar_mst_req[1].aw.id[3]` and `[5]` are untoggled.

The CPU-LSU splice `s_axi` carries a 3-bit ID (`dv/tb/tb_top.sv:1852`), so
this leaf sweeps 0..7 and the crossbars widen it with the master index on
their way out. The 6-bit external master (`dv/tb/tb_top.sv:1799`) is not used
here: it crosses the inbound filter, whose default state blocks it, and
opening that filter is the subject of its own tests.

Stimulus: repeat one read and write set over the SEP SRAM, the outbound and
inbound filter banks, the local-master alias-remap bank, the AP and STEE
output-remap banks, SEP_CPU_CTRL and the TRNG aperture, with `axi_id` swept
over 0..7. Accesses are issued one at a time, so no ID interleaving is
implied; the ID lanes are the target, not the reordering rules.

The writes are chosen so the sweep changes no state a later step depends on:
CLOCK_GATE_CTRL takes the implemented mask every fabric driver in this tree
writes and the SRAM word is scratch. No filter or remap region is enabled
anywhere in this leaf.

Response handling: the TRNG leg is terminated by an AXI-Lite error slave in
`hw/top/sep_ip_integration.sv`, so it answers with an error by design. Those
accesses take `allow_error` / `allow_unverified_write_resp` and
`SepCovStim.access` arms the AXI monitor for the tolerated beat.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE, SepCovStim
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    AP_BASE,
    INFILT_BASE,
    OUTFILT_BASE,
    STEE_BASE,
)

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
TRNG_BASE = sym("TRNG_APERTURE_MEM_BASE_ADDR")

# Scratch word on the SRAM port, clear of the burst apertures the other
# coverage leaves use at the bottom of the block.
SRAM_WORD = SRAM_BASE + 0x0840

# s_axi is a 3-bit ID master (dv/tb/tb_top.sv:1852).
ID_VALUES = tuple(range(8))

READ_ADDRS = (
    OUTFILT_BASE,
    INFILT_BASE,
    ALIAS_BASE,
    AP_BASE,
    STEE_BASE,
    CLOCK_GATE_CTRL,
    SRAM_WORD,
)

WRITE_ADDRS = (
    (CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE),
    (SRAM_WORD, 0x5A5A_A5A5),
)

WDATA_TRNG = 0xC0FF_EE00


@pyuvm.test()
class sep_cov_xbar_axid_sweep_test(sep_base_test):
    """AxID 0..7 on the fabric apertures. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for axi_id in ID_VALUES:
            for addr in READ_ADDRS:
                await stim.access(
                    op=SepAxiOp.READ,
                    addr=addr,
                    axi_id=axi_id,
                    name=f"cov_id{axi_id}_rd",
                )
            for addr, data in WRITE_ADDRS:
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=addr,
                    wdata=data,
                    axi_id=axi_id,
                    name=f"cov_id{axi_id}_wr",
                )
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=TRNG_BASE,
                wdata=WDATA_TRNG,
                axi_id=axi_id,
                allow_unverified_write_resp=True,
                name=f"cov_id{axi_id}_trng_wr",
            )
            await stim.access(
                op=SepAxiOp.READ,
                addr=TRNG_BASE,
                axi_id=axi_id,
                allow_error=True,
                name=f"cov_id{axi_id}_trng_rd",
            )
            self.logger.info("AxID=%d driven over the fabric apertures", axi_id)
