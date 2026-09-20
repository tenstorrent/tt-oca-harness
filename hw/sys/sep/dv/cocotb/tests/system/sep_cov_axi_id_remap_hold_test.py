# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AW and AR offered together into a saturated downstream, to drive the ID-remap holds."""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim, incr_bytes

# OTBN DMEM, behind `u_otbn_axi_dw_converter`
# (hw/sys/sep/rtl/sep_crypto_axi_interconnect.sv:331, AxiMaxReads=8 at :315).
# Entry 3 of the inbound allow windows in seq_lib/sep_cov_axi_burst_seq.py
# covers the crypto aperture, and OTBN DMEM is plain scratch storage while the
# core is idle, so a write there has no consequence beyond the stored word.
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv OCH_SEP_TOP_OTBN_DMEM_BASE_ADDR.
BASE = 0x1090_8000

# `axi_id_remap` reaches HoldAW, HoldAR and HoldAx only when a handshake it
# has already committed to is NOT taken downstream in the cycle it is offered.
# The existing concurrent leaf backpressures B and R, which stalls the
# responses but leaves AW-ready and AR-ready asserted, so the FSM returns to
# Ready every cycle and the hold arms stay dark.
#
# What deasserts AxREADY upstream of the remapper is a saturated downstream:
# the local crossbar carries MaxSlvTrans=4 per slave port and the crypto
# converter replicates AxiMaxReads=8 read slots, so more reads than that,
# held open by R backpressure, back the AR channel up to the remapper's master
# port. Writes are offered on the same inbound path throughout, so AW and AR
# are asking together while at least one of them cannot be taken.
N_READS = 12
N_WRITES = 12

BEATS = 4
BURST_BYTES = incr_bytes(BEATS)  # 32 B at size=3, also the address stride

# Long enough that every read is offered before the first R beat retires.
BACKPRESSURE_CYCLES = 600
ACCESS_TIMEOUT_NS = 60_000


@pyuvm.test()
class sep_cov_axi_id_remap_hold_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    `u_inbound_to_sep_id_remap` sits on the inbound path ahead of the local
    crossbar, so every SMN inbound access passes through it. Its FSM has three
    hold states for the case where it has allocated output IDs for an AW and an
    AR in the same cycle and the downstream takes neither, or only one.

    This leaf offers `N_WRITES` writes and `N_READS` reads together on the
    inbound master into one crypto aperture, with B and R held off long enough
    that the crossbar slave port and the converter read slots fill. Once they
    are full, AxREADY on the remapper's master port drops while both channels
    are still offered, which is the condition the hold states wait on.

    The accesses go through the VIP master rather than the UVM sequencer: the
    SEP AXI driver awaits each item to completion, so the sequencer cannot
    present AW and AR together.

    Saturating the path is the point, so an access that does not retire inside
    the bound is logged and tolerated rather than graded. No read data is
    compared, and the target words are OTBN DMEM scratch.
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
            for idx in range(max(N_WRITES, N_READS)):
                # Interleave the launches so AW and AR are offered in the same
                # cycles rather than in two separate runs of traffic.
                if idx < N_WRITES:
                    wr_addr = BASE + idx * BURST_BYTES
                    payload = rng.getrandbits(8 * BURST_BYTES).to_bytes(BURST_BYTES, "little")
                    tasks.append(
                        (
                            "write",
                            idx,
                            wr_addr,
                            cocotb.start_soon(
                                master.write_bytes_result(
                                    wr_addr,
                                    payload,
                                    size=SIZE_8B,
                                    burst=BURST_INCR,
                                    id=idx % 8,
                                    check_response=False,
                                    timeout_ns=ACCESS_TIMEOUT_NS,
                                    allow_timeout=True,
                                )
                            ),
                        )
                    )
                if idx < N_READS:
                    rd_addr = BASE + 0x400 + idx * BURST_BYTES
                    tasks.append(
                        (
                            "read",
                            idx,
                            rd_addr,
                            cocotb.start_soon(
                                master.read_bytes_result(
                                    rd_addr,
                                    BURST_BYTES,
                                    size=SIZE_8B,
                                    burst=BURST_INCR,
                                    id=idx % 8,
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
                "COV-STIM id_remap_hold_%s%d: %s 0x%08x id=%d beats=%d -> resp=%d%s",
                op,
                idx,
                op,
                addr,
                idx % 8,
                BEATS,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

        stim.record(
            "COV-AXI-ID-REMAP-HOLD",
            f"{N_WRITES} writes and {N_READS} reads offered together into one "
            "crypto aperture with B and R held off until the crossbar slave "
            "port and the converter read slots saturate",
        )
