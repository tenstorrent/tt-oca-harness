# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Multi-beat INCR bursts across both SEP crossbars.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `ar.len` / `aw.len` / `w.last` on `xbar_mst_req` and
`xbar_slv_req` of `hw/sys/sep/rtl/sep_local_axi_xbar.sv` and
`hw/sys/sep/rtl/crossbars/sep_system_peripherals_xbar.sv`, and on the
`sram_req_o` port. No master in the design issues `len > 0` today, so every
`len` bit on every crossbar port holds its reset value.

Stimulus: INCR reads and writes of 2, 4, 8, 16 and 32 beats at `size=3`
(16..256 bytes) into the SEP SRAM aperture, which crosses the local crossbar;
and INCR reads of the same beat counts into the local-master alias-remap
register bank, which crosses the system-peripherals crossbar. Every burst is
aligned to its own length and stays inside one 4 KiB page and inside the
addressed block, so no access is illegal AXI and none runs off the decoded
window. The register bank takes reads only: a burst write there would land
pattern data in remap control words.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim
from seq_lib.sep_fabric_csr_bank_seq import ALIAS_BASE

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")

# AxSIZE 3 is an 8-byte beat, the widest a 64-bit bus allows.
BEAT_SIZE = 3
BEAT_BYTES = 1 << BEAT_SIZE
BEAT_COUNTS = (2, 4, 8, 16, 32)

# Payload byte pattern for the SRAM writes; one repeated byte keeps the
# expression short at every burst length.
WDATA_BYTE = 0xA5


@pyuvm.test()
class sep_cov_xbar_burst_len_sweep_test(sep_base_test):
    """INCR bursts of 2..32 beats on both crossbars. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for beats in BEAT_COUNTS:
            length = beats * BEAT_BYTES
            addr = SRAM_BASE + length  # aligned to the burst length
            wdata = int.from_bytes(bytes([WDATA_BYTE]) * length, "little")
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=addr,
                wdata=wdata,
                length=length,
                size=BEAT_SIZE,
                burst=1,
                name=f"cov_sram_wr_{beats}b",
            )
            await stim.access(
                op=SepAxiOp.READ,
                addr=addr,
                length=length,
                size=BEAT_SIZE,
                burst=1,
                name=f"cov_sram_rd_{beats}b",
            )
            self.logger.info("SRAM INCR burst %d beats (%d bytes) driven", beats, length)

        for beats in BEAT_COUNTS:
            length = beats * BEAT_BYTES
            await stim.access(
                op=SepAxiOp.READ,
                addr=ALIAS_BASE,
                length=length,
                size=BEAT_SIZE,
                burst=1,
                name=f"cov_csr_rd_{beats}b",
            )
            self.logger.info("alias-remap bank INCR read burst %d beats driven", beats)
