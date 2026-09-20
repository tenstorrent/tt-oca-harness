# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Concurrent read and write bursts into SEP SRAM, to arbitrate the mem-port metadata."""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim, incr_bytes

# The SEP SRAM aperture, which `u_sram_memory_interface.u_axi_to_mem` serves
# through `i_axi_to_detailed_mem`
# (vendor/pulp-platform/axi/upstream/src/axi_to_detailed_mem.sv). Entry 0 of
# the inbound allow windows in seq_lib/sep_cov_axi_burst_seq.py covers it.
SRAM_BASE = 0x1000_0000

# Separate regions for the read stream and the write stream, so a concurrent
# write never lands under a concurrent read and the two are independent
# traffic rather than one ordered access pair.
WR_OFFSET = 0x0000
RD_OFFSET = 0x1000

# Beats per burst and how many burst pairs run together. `axi_to_detailed_mem`
# keeps one read-metadata counter and one write-metadata counter and arbitrates
# between them into a single memory port, with a lock held across a granted
# selection. Reaching the alternation and the lock needs read metadata and
# write metadata valid in the same cycle for more than one beat, so both sides
# are multi-beat and several pairs are in flight together.
BEATS = 8
BURST_BYTES = incr_bytes(BEATS)  # 64 B at size=3
N_PAIRS = 4

# Response backpressure, so the pairs stay in flight together instead of
# retiring one at a time.
BACKPRESSURE_CYCLES = 32
ACCESS_TIMEOUT_NS = 40_000


@pyuvm.test()
class sep_cov_axi_to_mem_rw_arb_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    `axi_to_detailed_mem` serialises AXI reads and writes onto one memory port.
    Its read-metadata and write-metadata paths, and the arbiter that selects
    between them and locks the selection while a grant is outstanding, only
    move when both sides are asking at once. The present suite drives SRAM
    bursts one direction at a time, so the arbiter always sees a single
    requester and its alternation and lock never move.

    This leaf issues `N_PAIRS` multi-beat INCR writes and `N_PAIRS` multi-beat
    INCR reads together on the SMN inbound master, to disjoint SRAM regions,
    with B and R backpressured so the pairs overlap. The reads and writes go
    through the VIP master rather than the UVM sequencer: the SEP AXI driver
    awaits each item to completion, so the sequencer cannot hold a read and a
    write in flight at the same time.

    Read data is logged, never compared. The write regions are scratch SRAM
    words and the read regions are a different SRAM page, so nothing here
    depends on, or disturbs, state any other leaf sets up.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        master = stim.master()
        drv = stim.timing_driver()
        drv.set_timing(
            AxiTimingProfile(b_ready_delay=BACKPRESSURE_CYCLES, r_ready_delay=BACKPRESSURE_CYCLES)
        )
        try:
            tasks = []
            for idx in range(N_PAIRS):
                wr_addr = SRAM_BASE + WR_OFFSET + idx * BURST_BYTES
                rd_addr = SRAM_BASE + RD_OFFSET + idx * BURST_BYTES
                payload = rng.getrandbits(8 * BURST_BYTES).to_bytes(BURST_BYTES, "little")
                tasks.append(
                    (
                        "write",
                        wr_addr,
                        cocotb.start_soon(
                            master.write_bytes_result(
                                wr_addr,
                                payload,
                                size=SIZE_8B,
                                burst=BURST_INCR,
                                id=idx,
                                check_response=False,
                                timeout_ns=ACCESS_TIMEOUT_NS,
                                allow_timeout=True,
                            )
                        ),
                    )
                )
                tasks.append(
                    (
                        "read",
                        rd_addr,
                        cocotb.start_soon(
                            master.read_bytes_result(
                                rd_addr,
                                BURST_BYTES,
                                size=SIZE_8B,
                                burst=BURST_INCR,
                                id=idx,
                                check_response=False,
                                timeout_ns=ACCESS_TIMEOUT_NS,
                                allow_timeout=True,
                            )
                        ),
                    )
                )
            results = [(op, addr, await task) for op, addr, task in tasks]
        finally:
            drv.set_timing(AxiTimingProfile())

        for op, addr, res in results:
            stim.driven += 1
            self.logger.info(
                "COV-STIM axi_to_mem_%s: %s 0x%08x size=3 burst=1 beats=%d -> resp=%d%s",
                op,
                op,
                addr,
                BEATS,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

        stim.record(
            "COV-AXI-TO-MEM-RW-ARB",
            f"{N_PAIRS} {BEATS}-beat INCR writes and {N_PAIRS} {BEATS}-beat INCR reads "
            "presented together into disjoint SRAM regions with B and R backpressured",
        )
