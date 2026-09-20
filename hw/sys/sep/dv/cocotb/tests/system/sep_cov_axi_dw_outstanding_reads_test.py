# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Eight outstanding reads, to reach the downsizer's transaction-slot replicates."""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim, incr_bytes

# OTBN DMEM, behind one crypto `axi_dw_downsizer`.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv OCH_SEP_TOP_OTBN_DMEM_BASE_ADDR.
BASE = 0x1090_8000

# AxiMaxReads=8 on the crypto downsizer group, so eight distinct ARIDs fill
# every transaction slot. Slot 0 is the only one the present suite reaches.
N_OUTSTANDING = 8
BEATS = 8
BURST_BYTES = incr_bytes(BEATS)  # 64 B, which is also the address stride

# R backpressure long enough for all eight ARs to be accepted before the first
# R beat retires. 400 cycles at the 5 ns system clock is 2 us, well inside the
# 50 us AXI timeout in env/sep_env_cfg.py.
R_BACKPRESSURE_CYCLES = 400
READ_TIMEOUT_NS = 40_000


@pyuvm.test()
class sep_cov_axi_dw_outstanding_reads_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Eight multi-beat INCR reads with eight distinct ARIDs are issued back to
    back on the SMN inbound master while RREADY is held low, so all eight are
    accepted before any R beat retires. `axi_dw_downsizer` replicates its
    transaction slot AxiMaxReads times and today only slot 0 is ever occupied.

    The reads go through the VIP master rather than the UVM sequencer: the
    SEP AXI driver awaits each item to completion, so the sequencer cannot
    hold more than one transaction in flight.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        master = stim.master()
        drv = stim.timing_driver()
        drv.set_timing(AxiTimingProfile(r_ready_delay=R_BACKPRESSURE_CYCLES))
        try:
            tasks = [
                cocotb.start_soon(
                    master.read_bytes_result(
                        BASE + idx * BURST_BYTES,
                        BURST_BYTES,
                        size=SIZE_8B,
                        burst=BURST_INCR,
                        id=idx,
                        check_response=False,
                        timeout_ns=READ_TIMEOUT_NS,
                        allow_timeout=True,
                    )
                )
                for idx in range(N_OUTSTANDING)
            ]
            results = [await task for task in tasks]
        finally:
            drv.set_timing(AxiTimingProfile())

        for idx, res in enumerate(results):
            stim.driven += 1
            self.logger.info(
                "COV-STIM outstanding_ar%d: read 0x%08x size=3 burst=1 beats=%d id=%d -> resp=%d%s",
                idx,
                BASE + idx * BURST_BYTES,
                BEATS,
                idx,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

        stim.record(
            "COV-AXI-DW-OUTSTANDING",
            f"{N_OUTSTANDING} concurrent {BEATS}-beat INCR reads on "
            f"{N_OUTSTANDING} distinct ARIDs under R backpressure",
        )
