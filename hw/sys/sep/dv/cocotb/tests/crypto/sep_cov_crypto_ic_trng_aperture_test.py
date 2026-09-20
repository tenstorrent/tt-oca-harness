# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Address the external-TRNG leg of the crypto AXI interconnect.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `trng_axi32_req` in
`hw/sys/sep/rtl/sep_crypto_axi_interconnect.sv:957`, the 64b->32b downsizer and
the AXI-to-AXI-Lite bridge that feed `ext_trng_axil_req_o`
(`sep_crypto_axi_interconnect.sv:977-1004`). No test addresses that leg, so all
32 of its signals are dark.

Stimulus: reads and writes from the CPU-LSU master across the TRNG aperture at
`TRNG_APERTURE_MEM_BASE_ADDR` (0x1091_7000, size 0x1000), whose register
layout `hw/sys/sep/regs/include/sep_trng.rdl` declares as an adopter-defined
external memory.

Response handling: the open tree has no external TRNG. `hw/top/sep_ip_integration.sv:761-771`
terminates `ext_trng_axil_req_i` with a `prim_axi_lite_err_slv`, so every
access on this leg is answered by an error slave. The reads are marked
`allow_error` so the environment tolerates that response instead of failing
the run, and the writes take the tolerant flag. This leaf grades neither the
response code nor the read data; what it drives is the interconnect leg in
front of the terminator.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim

TRNG_BASE = sym("TRNG_APERTURE_MEM_BASE_ADDR")
TRNG_SIZE = sym("TRNG_APERTURE_MEM_SIZE")

# 32-bit word offsets spread over the aperture, including the first and the
# last addressable word, so the leg's address lanes move rather than one
# constant offset being repeated.
OFFSETS = tuple(range(0, TRNG_SIZE, TRNG_SIZE // 16)) + (TRNG_SIZE - 4,)

WDATA = 0xC0FF_EE00


@pyuvm.test()
class sep_cov_crypto_ic_trng_aperture_test(sep_base_test):
    """Accesses across the TRNG aperture. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)

        for offset in OFFSETS:
            addr = TRNG_BASE + offset
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=addr,
                wdata=WDATA | offset,
                allow_unverified_write_resp=True,
                name=f"cov_trng_wr_{offset:03x}",
            )
            await stim.access(
                op=SepAxiOp.READ,
                addr=addr,
                allow_error=True,
                name=f"cov_trng_rd_{offset:03x}",
            )
        self.logger.info("TRNG aperture driven at %d offsets", len(OFFSETS))
