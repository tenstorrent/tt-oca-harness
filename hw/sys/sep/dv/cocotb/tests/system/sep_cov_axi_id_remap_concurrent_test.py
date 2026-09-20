# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Concurrent AW and AR on four IDs, to exhaust the inbound ID-remap table."""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim

# The dual scratch register banks: plain 64-bit R/W storage with no side
# effect, so a burst of writes there cannot perturb a later access.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv
# OCH_SEP_TOP_SEP_SCRATCH_COLD_BASE_ADDR = 0x10802000, 8 x 64-bit per bank.
#
# `u_inbound_to_sep_id_remap` sits on the inbound path ahead of the crossbar,
# so every inbound access passes through it whatever it addresses. The scratch
# banks are the target because they are the one window where a write has no
# consequence beyond the stored word.
SCRATCH_BASE = 0x1080_2000
SCRATCH_STRIDE = 0x8

# MaxSlvTrans is 4 on the local crossbar, so four IDs in flight in each
# direction is what runs the remap table out of free output IDs.
N_IDS = 4

# Response backpressure, so the handshakes the FSM has to hold are offered in
# a cycle where the downstream does not take them.
BACKPRESSURE_CYCLES = 64
ACCESS_TIMEOUT_NS = 40_000


@pyuvm.test()
class sep_cov_axi_id_remap_concurrent_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Four writes and four reads on four distinct AxIDs are presented together
    on the SMN inbound master with B and R backpressured, so `axi_id_remap`
    has AW and AR competing for the same free output ID and has to hold at
    least one of them. The present suite leaves AxID at 0 and retires one
    access at a time, so the allocation arbitration and the hold states are
    never entered.

    The accesses go through the VIP master: the SEP AXI driver retires one
    item before starting the next, so it cannot present AW and AR together.
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
            for idx in range(N_IDS):
                addr = SCRATCH_BASE + idx * SCRATCH_STRIDE
                payload = rng.getrandbits(64).to_bytes(8, "little")
                tasks.append(
                    (
                        "write",
                        idx,
                        addr,
                        cocotb.start_soon(
                            master.write_bytes_result(
                                addr,
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
                        idx,
                        addr,
                        cocotb.start_soon(
                            master.read_bytes_result(
                                addr,
                                8,
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
            results = [(op, idx, addr, await task) for op, idx, addr, task in tasks]
        finally:
            drv.set_timing(AxiTimingProfile())

        for op, idx, addr, res in results:
            stim.driven += 1
            self.logger.info(
                "COV-STIM id_remap_%s%d: %s 0x%08x id=%d -> resp=%d%s",
                op,
                idx,
                op,
                addr,
                idx,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

        stim.record(
            "COV-AXI-ID-REMAP",
            f"{N_IDS} writes and {N_IDS} reads presented together on {N_IDS} "
            "distinct AxIDs with B and R backpressured",
        )
