# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sram_auto_init_done_test (SMU_110).

With smc_disable_sram_auto_init_i at its 1'b0 default, the bring-up sweep is
awaited until smc_init_mem_done_o is high, a cold reset is then held until it
reaches the primary reset and the flag is required to clear, and the SMC
scratch-RAM zeroing is watched at its consumer after release: the
initialisation enable rises and the address counter advances, zeroing writes
reach the scratch RAM, and smc_init_mem_done_o asserts again and holds. The
covered geometry and latency are unstated (SF-046), so completion is awaited
under a testbench bound rather than compared against a cycle count.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_tb_pins import smu_scope

CPU_PATH = "u_smc.u_smc_cpu_wrapper.u_smc_cpu"
HOLD_REF_CYCLES = 16
RESET_BOUND_REF_CYCLES = 500
BUSY_BOUND_CYCLES = 4000
DONE_POLL_CYCLES = 64
DONE_POLL_BOUND = 8192
HOLD_DONE_CYCLES = 64


class smu_sram_auto_init_done_seq:
    """smc_init_mem_done_o after a real SRAM auto-initialisation."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard

    async def _await_done(self, since: str, zero_addr, init_enable) -> int:
        """Poll smc_init_mem_done_o high under a bound; returns the clk_smu it took."""
        dut = self.dut
        for poll in range(DONE_POLL_BOUND):
            await ClockCycles(dut.clk_smu_i, DONE_POLL_CYCLES)
            if sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"):
                return (poll + 1) * DONE_POLL_CYCLES
        raise AssertionError(
            f"TIMEOUT smc_init_mem_done_o never asserted {since}: "
            f"bound={DONE_POLL_BOUND * DONE_POLL_CYCLES} clk_smu "
            f"zero_addr=0x{sample(zero_addr, 'zero_addr'):x} enable={sample(init_enable, 'init_mem_enable')}"
        )

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        smu = smu_scope(dut)
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 8)

        sb.expect_true(
            "no +smc_scratch_ram_hex image, so the wrapper leaves smc_disable_sram_auto_init_i low",
            cocotb.plusargs.get("smc_scratch_ram_hex") is None,
        )
        disable = hier(smu, "smc_disable_sram_auto_init_i")
        init_enable = hier(smu, f"{CPU_PATH}.init_mem_enable")
        zero_addr = hier(smu, f"{CPU_PATH}.zero_addr")
        init_complete = hier(smu, f"{CPU_PATH}.init_mem_complete")
        sb.expect_eq(
            "smc_disable_sram_auto_init_i at its default at the SMU boundary",
            sample(disable, "smc_disable_sram_auto_init_i"),
            0,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        bringup_cycles = await self._await_done("after bring-up", zero_addr, init_enable)
        self.log.info(
            "smc_init_mem_done_o asserted within %d clk_smu of the sequence start; scratch writes %d",
            bringup_cycles,
            sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o"),
        )
        sb.expect_eq(
            "smc_init_mem_done_o is high after the bring-up sweep, before the cold reset",
            sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            1,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_eq(
            "initialisation complete before the cold reset",
            sample(init_complete, "init_mem_complete"),
            1,
        )

        dut.rst_cold_ni.value = 0
        for cycle in range(RESET_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 0:
                self.log.info("cold reset reached the primary reset after %d clk_ref", cycle)
                break
        else:
            raise AssertionError(
                f"TIMEOUT rst_primary_smc_clk_n_o never asserted: bound={RESET_BOUND_REF_CYCLES} clk_ref"
            )
        for _ in range(HOLD_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
        sb.expect_eq(
            "smc_init_mem_done_o clears under cold reset",
            sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            0,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_eq(
            "initialisation idle under cold reset",
            (sample(init_enable, "init_mem_enable"), sample(init_complete, "init_mem_complete")),
            (0, 0),
        )
        dut.rst_cold_ni.value = 1

        first_busy = None
        addr_samples: list[int] = []
        for cycle in range(BUSY_BOUND_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            if sample(init_enable, "init_mem_enable"):
                if first_busy is None:
                    first_busy = cycle
                addr_samples.append(sample(zero_addr, "zero_addr"))
                if len(addr_samples) >= 8:
                    break
        if first_busy is None:
            raise AssertionError(
                f"TIMEOUT auto-initialisation never started: bound={BUSY_BOUND_CYCLES} clk_smu "
                f"disable={sample(disable, 'smc_disable_sram_auto_init_i')}"
            )
        self.log.info(
            "initialisation enable seen %d clk_smu after release; zero_addr %s",
            first_busy,
            addr_samples,
        )
        sb.expect_true(
            "zeroing address counter advances while the initialisation runs",
            len(addr_samples) >= 2 and addr_samples[-1] > addr_samples[0],
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_eq(
            "smc_disable_sram_auto_init_i still low while the initialisation runs",
            sample(disable, "smc_disable_sram_auto_init_i"),
            0,
        )

        writes_at_start = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        done_cycle = await self._await_done("after the cold reset", zero_addr, init_enable)
        writes_at_done = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        self.log.info(
            "smc_init_mem_done_o asserted within %d clk_smu of the first enable; scratch writes %d -> %d",
            done_cycle,
            writes_at_start,
            writes_at_done,
        )
        sb.expect_eq(
            "smc_init_mem_done_o asserts once the initialisation completes",
            sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            1,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_eq(
            "smc_init_mem_done_o is the SMC initialisation-complete flag",
            sample(init_complete, "init_mem_complete"),
            1,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_true(
            "zeroing writes reached the scratch RAM before completion",
            writes_at_done > writes_at_start,
            evidence="CHK-SMU-MEMINIT-S1",
        )
        sb.expect_eq(
            "initialisation enable idle after completion", sample(init_enable, "init_mem_enable"), 0
        )
        held = 0
        for _ in range(HOLD_DONE_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            held += sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o")
        sb.expect_eq(
            f"smc_init_mem_done_o holds for {HOLD_DONE_CYCLES} clk_smu cycles",
            held,
            HOLD_DONE_CYCLES,
            evidence="CHK-SMU-MEMINIT-S1",
        )
