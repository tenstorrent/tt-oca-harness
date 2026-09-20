# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Multi-beat bursts into the SRAM and boot-ROM `axi_to_detailed_mem` adapters."""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import (
    BURST_INCR,
    SIZE_8B,
    SepCovAxiStim,
    incr_bytes,
    pattern,
)

# Scratch SRAM and the BL0 boot ROM, both behind an `axi_to_detailed_mem`
# adapter. Bases from hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv
# (OCH_SEP_TOP_SEP_SRAM_BASE_ADDR, OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR); the
# allocated spans are the SRAM and ROM rows of env/sep_axi_decode_map.py.
SRAM_BASE = 0x1000_0000
ROM_BASE = 0x1004_0000

# A 16-beat INCR burst at AxSIZE=3 is 128 bytes, which is what walks the
# adapter's read and write beat counters past their first value.
BEATS = 16
BURST_BYTES = incr_bytes(BEATS)

# Offsets used for the burst pair, far enough apart that the read and the
# write address different SRAM words while both are in flight.
RW_READ_OFFSET = 0x1000
RW_WRITE_OFFSET = 0x2000

# Response backpressure for the concurrent pair, so the adapter's read/write
# meta arbitration has to hold a selection instead of retiring each beat in
# the cycle it is offered.
THROTTLE_CYCLES = 1
PAIR_TIMEOUT_NS = 40_000


@pyuvm.test()
class sep_cov_axi_to_mem_burst_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Multi-beat INCR reads and writes into the SEP SRAM and boot-ROM memory
    adapters, then a read and a write issued together under R and B
    backpressure. `axi_to_detailed_mem` counts beats and arbitrates its read
    and write meta channels; a suite that only drives single-beat accesses one
    at a time leaves the counters and the arbitration lock at one value.

    Write payload comes from `env/sep_seeded_rng.py` and is never read back.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        await stim.burst(
            "sram_read_16beat",
            op=SepAxiOp.READ,
            addr=SRAM_BASE,
            length=BURST_BYTES,
            size=SIZE_8B,
            burst=BURST_INCR,
        )
        await stim.settle()
        await stim.burst(
            "sram_write_16beat",
            op=SepAxiOp.WRITE,
            addr=SRAM_BASE + RW_WRITE_OFFSET,
            length=BURST_BYTES,
            size=SIZE_8B,
            burst=BURST_INCR,
            wdata=pattern(rng, BURST_BYTES),
        )
        await stim.settle()
        await stim.burst(
            "rom_read_16beat",
            op=SepAxiOp.READ,
            addr=ROM_BASE,
            length=BURST_BYTES,
            size=SIZE_8B,
            burst=BURST_INCR,
        )
        await stim.settle()

        # The read and the write together, through the VIP master: the UVM
        # driver retires one item before starting the next, so it cannot
        # present both meta channels to the adapter at once.
        master = stim.master()
        drv = stim.timing_driver()
        drv.set_timing(
            AxiTimingProfile(r_ready_delay=THROTTLE_CYCLES, b_ready_delay=THROTTLE_CYCLES)
        )
        try:
            rd = cocotb.start_soon(
                master.read_bytes_result(
                    SRAM_BASE + RW_READ_OFFSET,
                    BURST_BYTES,
                    size=SIZE_8B,
                    burst=BURST_INCR,
                    check_response=False,
                    timeout_ns=PAIR_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            wr = cocotb.start_soon(
                master.write_bytes_result(
                    SRAM_BASE + RW_WRITE_OFFSET,
                    pattern(rng, BURST_BYTES).to_bytes(BURST_BYTES, "little"),
                    size=SIZE_8B,
                    burst=BURST_INCR,
                    check_response=False,
                    timeout_ns=PAIR_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            rd_res = await rd
            wr_res = await wr
        finally:
            drv.set_timing(AxiTimingProfile())

        stim.driven += 2
        self.logger.info(
            "COV-STIM sram_concurrent_rw: %d-beat read resp=%d%s, %d-beat write "
            "resp=%d%s, both under R/B backpressure",
            BEATS,
            rd_res.resp,
            " (no response, tolerated)" if rd_res.timed_out else "",
            BEATS,
            wr_res.resp,
            " (no response, tolerated)" if wr_res.timed_out else "",
        )

        stim.record(
            "COV-AXI-TO-MEM-BURST",
            f"{BEATS}-beat INCR reads and writes to SRAM and boot ROM, plus a "
            "concurrent read/write pair under response backpressure",
        )
