# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address the ERR_SLV leg of the sep_system_csr demux.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): master port 8 of `system_csr_axil_demux` in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv`, which
`sep_pkg::system_csr_demux_select_t` names `ERR_SLV`
(`hw/sys/sep/rtl/sep_pkg.sv:297`) and the decode selects in its final `else`
arm. `sep_system_csr_axil_reqs[8]` and `sep_system_csr_axil_resps[8]` are
wholly untoggled in the merged report -- `aw_valid`, `ar_valid`, `b_valid` and
`r_valid` included -- so the leg and the error slave behind it have never been
driven. Every other of the nine legs is live.

The address rule that brings traffic to `sep_system_csr` is 0x10A1_0000 ..
0x10A5_0000 (`hw/sys/sep/rtl/crossbars/sep_system_peripherals_xbar.sv:18`),
which is wider than the sub-blocks the CSR decode recognises. An access inside
that rule but outside every sub-block is legal AXI that the crossbar delivers
and the CSR decode answers from its own error slave. This is a decode hole,
not an unsupported shape.

Stimulus: reads and writes at three holes, each derived from a bank end rather
than written as a literal so a register move cannot leave them stale --
one word past the last STEE output-remap region, one word past the last
outbound filter slot, and one word past the last inbound filter slot.

Response handling: the leg exists to answer with an error, so every access
here is expected to come back non-OKAY. The reads take `allow_error` and the
writes `allow_unverified_write_resp`; `SepCovStim.access` arms the AXI monitor
for each tolerated read beat. This leaf grades neither the response code nor
the read data. Nothing it writes lands in a register: the hole has no storage.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import (
    FILTER_STRIDE,
    INFILT_BASE,
    INFILT_ENTRIES,
    OUTFILT_BASE,
    OUTFILT_ENTRIES,
    SepCovStim,
)
from seq_lib.sep_fabric_csr_bank_seq import REMAP_REGIONS, REMAP_STRIDE, STEE_BASE

# Addresses inside the system_csr crossbar rule that no CSR sub-block decodes.
# Each sits immediately past the end of a bank, so it is inside the rule and
# outside every `if` arm of the sep_system_csr decode.
HOLE_ADDRS = (
    STEE_BASE + REMAP_REGIONS * REMAP_STRIDE,
    OUTFILT_BASE + OUTFILT_ENTRIES * FILTER_STRIDE,
    INFILT_BASE + INFILT_ENTRIES * FILTER_STRIDE,
)

# Word offsets within each hole, so the leg's low address lanes move.
HOLE_OFFSETS = (0x00, 0x04, 0x08, 0x10)

WDATA = 0xDEAD_0000


@pyuvm.test()
class sep_cov_csr_demux_err_slv_leg_test(sep_base_test):
    """Reads and writes down the system-CSR ERR_SLV leg. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for hole in HOLE_ADDRS:
            for offset in HOLE_OFFSETS:
                addr = hole + offset
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=addr,
                    wdata=WDATA | offset,
                    allow_unverified_write_resp=True,
                    name=f"cov_errslv_wr_{addr:08x}",
                )
                await stim.access(
                    op=SepAxiOp.READ,
                    addr=addr,
                    allow_error=True,
                    name=f"cov_errslv_rd_{addr:08x}",
                )
            self.logger.info("system-CSR decode hole 0x%08x driven", hole)
