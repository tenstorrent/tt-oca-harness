# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Isolate a full-AXI port with traffic outstanding, to drive the drain states."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim
from seq_lib.sep_sw_reset_seq import SepSwReset

# The ABR aperture. `u_abr_host_isolate` (sep_crypto_axi_interconnect.sv:1027)
# is the only full-AXI `axi_isolate` instance in SEP, and it sits on this
# port. Its `isolate_i` is `isolate_req_i.host_abr`, which sep_reset_ctrl.sv:233
# drives from `u_abr_isolate_seq`, whose request input is SW_RESET_N.abr --
# so clearing that CSR bit is the frontdoor isolate request.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv OCH_SEP_TOP_ABR_BASE_ADDR.
ABR_BASE = 0x1094_0000

# Accesses left outstanding across the isolate request.
N_OUTSTANDING = 2

# Backpressure so the accesses are still in flight when the request asserts,
# and a short gap so the request lands after AxVALID rises.
BACKPRESSURE_CYCLES = 64
REQUEST_DELAY_CYCLES = 2
SETTLE_CYCLES = 200

# A port held isolated refuses or drops what is in flight, so these accesses
# may not retire. That is the state being driven, not a wedge to grade: the
# leaf tolerates a missing response and logs it.
ACCESS_TIMEOUT_NS = 20_000


@pyuvm.test()
class sep_cov_axi_isolate_drain_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    `axi_isolate_inner` holds and drains the AW and AR channels and clears its
    outstanding counters before it reports isolated. Reaching those states
    needs the isolate request to arrive while a transaction is in flight; the
    present suite asserts the ABR software reset only with the bus quiet, so
    the FSM goes straight from Idle to Isolated.

    The leaf drives the request twice: once with an AW and an AR outstanding
    and the responses backpressured, and once with the traffic idle, so both
    entry paths are driven. Whether an in-flight access retires is logged and
    not graded.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        swrst = SepSwReset(self)
        master = stim.master()
        drv = stim.timing_driver()
        clk = cocotb.top.clk_i

        # --- isolate with traffic in flight ---------------------------------
        drv.set_timing(
            AxiTimingProfile(b_ready_delay=BACKPRESSURE_CYCLES, r_ready_delay=BACKPRESSURE_CYCLES)
        )
        tasks = []
        try:
            for idx in range(N_OUTSTANDING):
                addr = ABR_BASE + idx * 8
                tasks.append(
                    (
                        "write",
                        addr,
                        cocotb.start_soon(
                            master.write_bytes_result(
                                addr,
                                rng.getrandbits(64).to_bytes(8, "little"),
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
            # The request one cycle pair after AxVALID rises, so it arrives
            # while the channels are offered and not yet accepted.
            await ClockCycles(clk, REQUEST_DELAY_CYCLES)
            await swrst.park("abr")
            results = [(op, addr, await task) for op, addr, task in tasks]
        finally:
            drv.set_timing(AxiTimingProfile())

        for op, addr, res in results:
            stim.driven += 1
            self.logger.info(
                "COV-STIM isolate_inflight_%s: %s 0x%08x -> resp=%d%s",
                op,
                op,
                addr,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

        await ClockCycles(clk, SETTLE_CYCLES)
        await swrst.release("abr")
        await ClockCycles(clk, SETTLE_CYCLES)

        # --- isolate with the port quiet ------------------------------------
        await swrst.park("abr")
        await ClockCycles(clk, SETTLE_CYCLES)
        await swrst.release("abr")
        await ClockCycles(clk, SETTLE_CYCLES)
        self.logger.info(
            "COV-STIM isolate_idle: ABR isolate asserted and released with the port quiet"
        )

        stim.record(
            "COV-AXI-ISOLATE-DRAIN",
            "ABR isolate request asserted with an AW and an AR outstanding "
            "under backpressure, then again with the port quiet",
        )
