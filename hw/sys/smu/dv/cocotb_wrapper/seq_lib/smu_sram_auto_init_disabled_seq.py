# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sram_auto_init_disabled_test. SEP=0, no Force.

The complement of smu_sram_auto_init_done_test. That leaf runs with
``smc_disable_sram_auto_init_i`` low and watches the SMC scratch-RAM zeroing
sweep run to completion; this one runs the same cold reset with the input
high: the initialisation enable must never rise and no zeroing write may
reach the scratch RAM, which is the input's stated purpose (``smu.adoc``,
``cpu.adoc``). Neither document says what ``smc_init_mem_done_o`` does when
the sweep is held off, so its behaviour after the release is recorded --
whether and when it rose, and how it held -- and carries no token: a
specification statement, not a reading of the implementation, is what would
turn that record into a claim.

The bench raises the input when a test supplies ``+smc_scratch_ram_hex``,
because the sweep would otherwise overwrite the image; the testlist entry
supplies one and the sequence refuses to run without it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_tb_pins import smu_scope

CPU_PATH = "u_smc.u_smc_cpu_wrapper.u_smc_cpu"
HOLD_REF_CYCLES = 16
RESET_BOUND_REF_CYCLES = 500
DONE_BOUND_CYCLES = 8192
QUIET_SAMPLES = 2048


class smu_sram_auto_init_disabled_seq:
    """No zeroing sweep and no zeroing write with the SRAM auto-initialisation disabled."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        smu = smu_scope(dut)
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_true(
            "the testlist supplies +smc_scratch_ram_hex, which is what raises the input",
            cocotb.plusargs.get("smc_scratch_ram_hex") is not None,
        )
        disable = hier(smu, "smc_disable_sram_auto_init_i")
        init_enable = hier(smu, f"{CPU_PATH}.init_mem_enable")
        init_complete = hier(smu, f"{CPU_PATH}.init_mem_complete")
        sb.expect_eq(
            "smc_disable_sram_auto_init_i reads high at the SMU boundary",
            sample(disable, "smc_disable_sram_auto_init_i"),
            1,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )

        dut.rst_cold_ni.value = 0
        for cycle in range(RESET_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 0:
                self.log.info("cold reset reached the primary reset after %d clk_ref", cycle)
                break
        else:
            raise AssertionError(
                f"TIMEOUT rst_primary_smc_clk_n_o never asserted: "
                f"bound={RESET_BOUND_REF_CYCLES} clk_ref"
            )
        for _ in range(HOLD_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
        sb.expect_eq(
            "smc_init_mem_done_o clears under cold reset",
            sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            0,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )
        writes_before = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        dut.rst_cold_ni.value = 1

        # Watch the enable over a fixed window while the sweep is held off; it
        # must never rise. What smc_init_mem_done_o does in that window is
        # recorded alongside, without a compare (module docstring).
        done_cycle = None
        done_high = 0
        enable_seen = 0
        for cycle in range(DONE_BOUND_CYCLES + QUIET_SAMPLES):
            await RisingEdge(dut.clk_smu_i)
            enable_seen |= sample(init_enable, "init_mem_enable")
            done = sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o")
            if done and done_cycle is None:
                done_cycle = cycle
            if cycle >= DONE_BOUND_CYCLES:
                done_high += done
        sb.expect_eq(
            f"the zeroing sweep never starts across {DONE_BOUND_CYCLES + QUIET_SAMPLES} clk_smu "
            "cycles after the release",
            enable_seen,
            0,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )
        self.log.info(
            "OBSERVED-ONLY smc_init_mem_done_o with the sweep held off: %s; high on %d of the "
            "last %d cycles of the window (init_mem_complete=%d). No specification states the "
            "done behaviour for a disabled sweep, so this is recorded, not compared",
            f"rose {done_cycle} clk_smu after the release"
            if done_cycle is not None
            else f"did not rise within {DONE_BOUND_CYCLES + QUIET_SAMPLES} clk_smu",
            done_high,
            QUIET_SAMPLES,
            sample(init_complete, "init_mem_complete"),
        )
        writes_after = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        self.log.info("scratch writes %d -> %d across the window", writes_before, writes_after)
        sb.expect_eq(
            "no zeroing write reached the scratch RAM",
            writes_after,
            writes_before,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )
