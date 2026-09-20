# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Back-pressure B on writes aimed at the Adams Bridge register window, so the
AXI-to-AHB bridge in front of it has to park a completed write.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. Nothing written here is read back or compared.

Target, `vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/lib/axi4_to_ahb.sv`,
the instance at `hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:91`. Its DATA_WR case
(:350) picks the next state as

    buf_nxtstate = (ahb_hresp_q | ~axi_bready) ? DONE_WR : ...

`ahb_hresp` is constant OKAY in this integration (see the waiver note in
`docs/`, `abr_reg.sv:2413` and `:2551` tie the register file's write and read
error outputs to zero, so `abr_ahb_slv_sif.sv:138` never drives H_ERROR), which
leaves `~axi_bready` as the only way into DONE_WR. The DONE_WR state (:363) and
both of its arcs, DATA_WR -> DONE_WR and DONE_WR -> IDLE, are dark because every
leaf that writes an ABR register accepts B immediately.

Stimulus: a run of single-beat writes into the ABR window with the inbound
master's B-ready delay set long, so B is offered in a cycle the master does not
take it and the bridge has to hold the completed write. The writes go to
`ABR_ENTROPY`, which is a plain input-word array the engine only samples when a
command is issued, so a run of writes there has no effect beyond the stored
words and no command is left running.

The window is opened through the inbound filter by `SepCovAxiStim.open_windows`
(entry 4 covers 0x1094_0000..0x1094_FFFF). The filter is programmed from the
CPU-LSU side, so this stimulus never reprograms the gate it drives through.

RANDCFG: the written words come from the run seed through `SepSeededRng`. They
are not a key, nonce or token, and nothing leaves the simulation.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import ABR_ENTROPY, ENTROPY_WORDS
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_4B, SepCovAxiStim

# Long enough that B is presented while the master is still refusing it, which
# is what holds the bridge in DONE_WR.
B_READY_DELAY_CYCLES = 96

# Several writes in flight, so the bridge sees the stall on more than the one
# write that happens to be first out of reset.
WRITES = 24
ACCESS_TIMEOUT_NS = 200_000


@pyuvm.test()
class sep_cov_abr_ahb_bresp_stall_test(sep_base_test):
    """ABR register writes with B held off. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        master = stim.master()
        drv = stim.timing_driver()
        drv.set_timing(AxiTimingProfile(b_ready_delay=B_READY_DELAY_CYCLES))
        try:
            for idx in range(WRITES):
                addr = ABR_ENTROPY + (idx % ENTROPY_WORDS) * 4
                payload = rng.getrandbits(32).to_bytes(4, "little")
                res = await master.write_bytes_result(
                    addr,
                    payload,
                    size=SIZE_4B,
                    burst=BURST_INCR,
                    check_response=False,
                    timeout_ns=ACCESS_TIMEOUT_NS,
                    allow_timeout=True,
                )
                stim.driven += 1
                self.logger.info(
                    "COV-STIM abr_ahb_bstall%d: write 0x%08x -> resp=%d%s",
                    idx,
                    addr,
                    res.resp,
                    " (no response, tolerated)" if res.timed_out else "",
                )
        finally:
            drv.set_timing(AxiTimingProfile())

        stim.record(
            "COV-ABR-AHB-BSTALL",
            f"{WRITES} single-beat writes into the ABR window with B held off "
            f"for {B_READY_DELAY_CYCLES} cycles",
        )
