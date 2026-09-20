# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WRAP bursts into the SEP SRAM aperture.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `aw.burst[1]` and `ar.burst[1]` on `xbar_mst_req`,
`xbar_slv_req` and `sram_req_o`. AXI AxBURST reaches WRAP only at encoding
0b10, and no SEP sequence has used it, so that bit is dark on every crossbar
port.

Stimulus: WRAP reads and writes of 4 and 8 beats at `size=3` into the SEP SRAM
aperture. AMBA AXI4 (IHI 0022) allows WRAP only at 2, 4, 8 or 16 beats with the
start address aligned to the beat size, and the burst must not leave its wrap
boundary; each access here is placed on a boundary equal to its own total
length, which satisfies both. `SepAxiAccessSeq` already carries the `burst`
argument.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")

# AXI AxBURST encodings (IHI 0022): FIXED=0, INCR=1, WRAP=2.
BURST_WRAP = 2

BEAT_SIZE = 3
BEAT_BYTES = 1 << BEAT_SIZE
WRAP_BEATS = (4, 8)

WDATA_BYTE = 0x5A


@pyuvm.test()
class sep_cov_xbar_wrap_burst_test(sep_base_test):
    """WRAP bursts of 4 and 8 beats to SRAM. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)

        for beats in WRAP_BEATS:
            length = beats * BEAT_BYTES
            addr = SRAM_BASE + length  # on the wrap boundary for this length
            wdata = int.from_bytes(bytes([WDATA_BYTE]) * length, "little")
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=addr,
                wdata=wdata,
                length=length,
                size=BEAT_SIZE,
                burst=BURST_WRAP,
                name=f"cov_wrap_wr_{beats}b",
            )
            await stim.access(
                op=SepAxiOp.READ,
                addr=addr,
                length=length,
                size=BEAT_SIZE,
                burst=BURST_WRAP,
                name=f"cov_wrap_rd_{beats}b",
            )
            self.logger.info("SRAM WRAP burst %d beats (%d bytes) driven", beats, length)
