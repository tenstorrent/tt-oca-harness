# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Present writes and reads together on the Adams Bridge register window with
the read channel held off, so the AXI-to-AHB bridge chains a write straight
into a read and the inbound ID remapper has to hold an address.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more. Nothing read here is compared against an expectation.

Two targets.

`vendor/chipsalliance/Cores-VeeR-EL2/upstream/design/lib/axi4_to_ahb.sv`, the
instance at `hw/sys/sep/rtl/sep_crypto_abr_wrapper.sv:91`. Its DATA_WR case
(:350) chains straight into the next command:

    buf_nxtstate = ... ((master_valid & master_ready) ?
                        ((master_opc[2:1] == 2'b01) ? CMD_WR : CMD_RD) : IDLE)

`master_valid` is `wr_cmd_vld | axi_arvalid` (:254) and `master_opc` is the
write encoding whenever a buffered write is pending (:257), so the CMD_RD leg
needs an AR presented in the cycle a write retires with no further write queued.
DATA_WR -> CMD_WR and DATA_WR -> IDLE are covered; DATA_WR -> CMD_RD is not,
because the suite's ABR leaves retire one access at a time.

`vendor/pulp-platform/axi/upstream/src/axi_id_remap.sv`, the inbound instance.
Its Ready case falls into HoldAR, HoldAW or HoldAx (:289-296) only when an
address channel it has already driven valid is refused by the downstream in the
same cycle. All three hold states and all eight of their arcs are dark.
Downstream `ar_ready` drops once the crossbar's outstanding-transaction budget
for a slave is used up, which is what a deep run of reads with R held off does.

Stimulus: writes and reads to the ABR window started together through the VIP
master, with both R and B back-pressured, on several AxIDs. `ABR_ENTROPY` is a
plain input-word array the engine only samples when a command is issued, so a
run of writes there has no effect beyond the stored words; the reads target
`MLDSA_NAME`, which is a read-only identification register.

The window is opened through the inbound filter by `SepCovAxiStim.open_windows`
(entry 4 covers 0x1094_0000..0x1094_FFFF). The filter is programmed from the
CPU-LSU side, so this stimulus never reprograms the gate it drives through.

RANDCFG: the written words come from the run seed through `SepSeededRng`. They
are not a key, nonce or token, and nothing leaves the simulation.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_abr_keygen_seq import ABR_ENTROPY, ABR_NAME0, ENTROPY_WORDS
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_4B, SepCovAxiStim

# Deep enough that the reads outlive the writes and the downstream read budget
# is used up while an AW is still being presented.
R_READY_DELAY_CYCLES = 160
B_READY_DELAY_CYCLES = 24

# MaxSlvTrans on the local crossbar is 4, so four IDs in each direction is what
# runs the remap table out of free output IDs.
N_IDS = 4
ROUNDS = 6
ACCESS_TIMEOUT_NS = 400_000


@pyuvm.test()
class sep_cov_abr_ahb_rw_interleave_test(sep_base_test):
    """Interleaved ABR writes and reads with R and B held off. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        master = stim.master()
        drv = stim.timing_driver()
        drv.set_timing(
            AxiTimingProfile(
                r_ready_delay=R_READY_DELAY_CYCLES, b_ready_delay=B_READY_DELAY_CYCLES
            )
        )
        try:
            for rnd in range(ROUNDS):
                await self._round(master, rng, stim, rnd)
        finally:
            drv.set_timing(AxiTimingProfile())

        stim.record(
            "COV-ABR-AHB-RW-INTERLEAVE",
            f"{ROUNDS} rounds of {N_IDS} writes and {N_IDS} reads started together on "
            "the ABR window with R and B held off",
        )

    async def _round(self, master, rng: SepSeededRng, stim: SepCovAxiStim, rnd: int) -> None:
        tasks = []
        for idx in range(N_IDS):
            waddr = ABR_ENTROPY + ((rnd * N_IDS + idx) % ENTROPY_WORDS) * 4
            payload = rng.getrandbits(32).to_bytes(4, "little")
            tasks.append(
                (
                    "write",
                    idx,
                    waddr,
                    cocotb.start_soon(
                        master.write_bytes_result(
                            waddr,
                            payload,
                            size=SIZE_4B,
                            burst=BURST_INCR,
                            id=idx,
                            check_response=False,
                            timeout_ns=ACCESS_TIMEOUT_NS,
                            allow_timeout=True,
                        )
                    ),
                )
            )
            raddr = ABR_NAME0 + (idx % 2) * 4
            tasks.append(
                (
                    "read",
                    idx,
                    raddr,
                    cocotb.start_soon(
                        master.read_bytes_result(
                            raddr,
                            4,
                            size=SIZE_4B,
                            burst=BURST_INCR,
                            id=idx,
                            check_response=False,
                            timeout_ns=ACCESS_TIMEOUT_NS,
                            allow_timeout=True,
                        )
                    ),
                )
            )
        results = [(op, idx, addr, await task) for op, idx, addr, task in tasks]

        for op, idx, addr, res in results:
            stim.driven += 1
            self.logger.info(
                "COV-STIM abr_ahb_rw r%d: %s 0x%08x id=%d -> resp=%d%s",
                rnd,
                op,
                addr,
                idx,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )
