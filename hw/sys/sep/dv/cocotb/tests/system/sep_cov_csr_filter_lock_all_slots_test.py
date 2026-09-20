# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lock every filter slot, then write each locked slot again.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the per-slot `locked_reg_req` / `locked_reg_resp` signals and
the `prim_axi_lite_err_slv` instance inside `gen_outbound_filter_reg` and
`gen_inbound_filter_reg` in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_csr.sv`, plus
`FILTER_CONFIG.locked` on all 48 slots. A locked slot routes a further write
to that error slave, and that is the only path on which `locked_reg_req`
asserts; the existing bank sweep locks two slots per seed.

Stimulus: set FILTER_CONFIG.locked -- bit 31 of the FILTER_CONFIG high word,
FILTER_CONFIG[63], write-once-set -- on each of the 32 outbound and 16 inbound
slots, then issue one more FILTER_CONFIG write to each locked slot with the
response tolerated. The lock holds until reset, so this leaf must not share a
run with `sep_cov_csr_filter_slot_data_walk_test`.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_stimulus_seq import (
    FILTER_CONFIG,
    FILTER_LOCK_HI_BIT,
    INFILT_ENTRIES,
    OUTFILT_ENTRIES,
    SepCovStim,
)

# Payload of the post-lock write. Any value reaches the error slave; a
# recognisable one makes the access easy to find in a waveform.
POST_LOCK_WDATA = 0xA5A5_A5A5


@pyuvm.test()
class sep_cov_csr_filter_lock_all_slots_test(sep_base_test):
    """Lock all 48 filter slots and re-write each. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        for inbound, count in ((False, OUTFILT_ENTRIES), (True, INFILT_ENTRIES)):
            bank = "inbound" if inbound else "outbound"
            for index in range(count):
                slot = stim.filter_slot(inbound=inbound, index=index)
                await stim._wr(slot + FILTER_CONFIG + 4, FILTER_LOCK_HI_BIT)
            self.logger.info("%s filter: locked %d slots", bank, count)

            for index in range(count):
                slot = stim.filter_slot(inbound=inbound, index=index)
                # The slot is locked, so this write is answered by the slot's
                # error slave rather than by the register file. The response is
                # tolerated and not graded.
                await stim.access(
                    op=SepAxiOp.WRITE,
                    addr=slot + FILTER_CONFIG,
                    wdata=POST_LOCK_WDATA,
                    allow_unverified_write_resp=True,
                    name=f"cov_locked_{bank}_{index}",
                )
            self.logger.info("%s filter: re-wrote %d locked slots", bank, count)
