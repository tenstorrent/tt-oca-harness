# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sram_auto_init_disabled_test. No force.

The complement of smu_sram_auto_init_done_test. That leaf runs with
``smc_disable_sram_auto_init_i`` low and watches the SMC scratch-RAM zeroing
sweep run to completion; this one runs the same cold reset with the input
high: the initialisation enable must never rise and no zeroing write may
reach the scratch RAM, which is the input's stated purpose (``smu.adoc``,
``cpu.adoc``). ``cpu.adoc`` (Reset and Boot) states that ``smc_init_mem_done_o``
reports either completion or bypass, so with the sweep held off the output
must still rise after the cold reset releases and then hold: the leaf
requires the rise within ``BYPASS_DONE_BOUND_CYCLES`` of the release and the
output high on every sampled cycle after the rise to the end of the window
(``CHK-SMU-MEMINIT-BYPASS-DONE``).

The bound is twice the reset-release pipeline the rise crosses, counted in
``clk_smu`` with the bench's ``clk_ref``/``clk_smu`` ratio: the SMC reset
unit's cold-reset de-glitcher passes the release on the next ``clk_ref`` and
its extender then holds the primary reset ``COLD_RESET_EXTEND_REF_CYCLES``
more; the primary reset deasserts through a ``PRIMARY_RESET_SYNC_CYCLES``
synchroniser on the SMC clock; the eFuse controller sets its sense-done flop
on the next cycle under ``+skip_fuse_sense`` and releases the fuse reset
through a two-flop synchroniser (``FUSE_RESET_RELEASE_CYCLES``); and the
zero-fill sequencer, reset by that fuse reset, steps from idle to its terminal
state on one cycle and raises ``init_mem_complete`` on the next
(``BYPASS_DONE_CYCLES``).

The cold-reset leg compares only that the output reads low while the reset is
asserted and records what it read beforehand. The clear of an output known to
be high is the sibling's: it runs the sweep to completion, requires the output
high, and only then asserts the cold reset.

The bench raises the input when a test supplies ``+smc_scratch_ram_hex``,
because the sweep would otherwise overwrite the image; the testlist entry
supplies one and the sequence refuses to run without it.

A last leg lowers the input through the bench's ``tb_smc_sram_auto_init_restore``
and runs a second cold reset: the initialisation enable rises and zeroing
writes reach the scratch RAM, the behaviour smu_sram_auto_init_done_test proves
for a run that never raised the input.
"""

from __future__ import annotations

import math

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_tb_pins import smu_scope

CPU_PATH = "u_smc.u_smc_cpu_wrapper.u_smc_cpu"
HOLD_REF_CYCLES = 16
RESET_BOUND_REF_CYCLES = 500
DONE_BOUND_CYCLES = 8192
QUIET_SAMPLES = 2048
COLD_RESET_DEGLITCH_REF_CYCLES = 1
COLD_RESET_EXTEND_REF_CYCLES = 255
PRIMARY_RESET_SYNC_CYCLES = 4
FUSE_RESET_RELEASE_CYCLES = 1 + 2
BYPASS_DONE_CYCLES = 2


def bypass_done_bound_cycles(ref_clk_period_ns: float, smu_clk_period_ns: float) -> int:
    """Twice the cold-reset release pipeline to init_mem_complete, in clk_smu."""
    ref_cycles = COLD_RESET_DEGLITCH_REF_CYCLES + COLD_RESET_EXTEND_REF_CYCLES
    smu_cycles = PRIMARY_RESET_SYNC_CYCLES + FUSE_RESET_RELEASE_CYCLES + BYPASS_DONE_CYCLES
    return 2 * (math.ceil(ref_cycles * ref_clk_period_ns / smu_clk_period_ns) + smu_cycles)


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

        done_before_reset = sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o")

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
            "smc_init_mem_done_o reads low while the cold reset is asserted",
            sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o"),
            0,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )
        self.log.info(
            "OBSERVED-ONLY smc_init_mem_done_o read %d before the cold reset; cpu.adoc states "
            "that the output reports either completion or bypass, and this leg compares only "
            "the low level under reset; smu_sram_auto_init_done_test carries the "
            "clear of an output it first requires high",
            done_before_reset,
        )
        writes_before = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        dut.rst_cold_ni.value = 1

        # Watch the enable over a fixed window while the sweep is held off; it
        # must never rise. smc_init_mem_done_o must rise within the bound and
        # stay high on every later sample of the same window.
        window = DONE_BOUND_CYCLES + QUIET_SAMPLES
        bound = bypass_done_bound_cycles(
            self.test.cfg.ref_clk_period_ns, self.test.cfg.smu_clk_period_ns
        )
        done_cycle = None
        done_high = 0
        enable_seen = 0
        for cycle in range(window):
            await RisingEdge(dut.clk_smu_i)
            enable_seen |= sample(init_enable, "init_mem_enable")
            done = sample(dut.smc_init_mem_done_o, "smc_init_mem_done_o")
            if done and done_cycle is None:
                done_cycle = cycle
            if done_cycle is not None:
                done_high += done
        sb.expect_eq(
            f"the zeroing sweep never starts across {window} clk_smu cycles after the release",
            enable_seen,
            0,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )
        hold_samples = window - done_cycle if done_cycle is not None else 0
        self.log.info(
            "CHK-SMU-MEMINIT-BYPASS-DONE smc_init_mem_done_o with the sweep held off: %s "
            "(bound=%d clk_smu); high on %d of the %d samples from the rise to the end of the "
            "%d-cycle window (init_mem_complete=%d)",
            f"rose {done_cycle} clk_smu after the release"
            if done_cycle is not None
            else "did not rise within the window",
            bound,
            done_high,
            hold_samples,
            window,
            sample(init_complete, "init_mem_complete"),
        )
        sb.expect_eq(
            "CHK-SMU-MEMINIT-BYPASS-DONE smc_init_mem_done_o reports the bypass: it rises within "
            "the bound and holds on every sampled cycle after the rise",
            (done_cycle is not None and done_cycle < bound, done_high == hold_samples),
            (True, True),
            evidence="CHK-SMU-MEMINIT-BYPASS-DONE",
        )
        writes_after = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        self.log.info("scratch writes %d -> %d across the window", writes_before, writes_after)
        sb.expect_eq(
            "no zeroing write reached the scratch RAM",
            writes_after,
            writes_before,
            evidence="CHK-SMU-MEMINIT-DISABLED",
        )

        dut.tb_smc_sram_auto_init_restore.value = 1
        await ClockCycles(dut.clk_smu_i, 4)
        restored = sample(disable, "smc_disable_sram_auto_init_i")
        dut.rst_cold_ni.value = 0
        for cycle in range(RESET_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            if sample(dut.rst_primary_smc_clk_n_o, "rst_primary_smc_clk_n_o") == 0:
                self.log.info("second cold reset reached the primary reset after %d clk_ref", cycle)
                break
        else:
            raise AssertionError(
                f"TIMEOUT rst_primary_smc_clk_n_o never asserted on the second cold reset: "
                f"bound={RESET_BOUND_REF_CYCLES} clk_ref"
            )
        for _ in range(HOLD_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
        writes_before = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        dut.rst_cold_ni.value = 1
        enable_seen = 0
        for _ in range(DONE_BOUND_CYCLES):
            await RisingEdge(dut.clk_smu_i)
            enable_seen |= sample(init_enable, "init_mem_enable")
            if enable_seen:
                break
        await ClockCycles(dut.clk_smu_i, 64)
        writes_after = sample(dut.smc_scratch_write_count_dv_o, "smc_scratch_write_count_dv_o")
        self.log.info(
            "CHK-SMU-MEMINIT-RESTORED input=%d enable_seen=%d writes %d -> %d",
            restored,
            enable_seen,
            writes_before,
            writes_after,
        )
        sb.expect_eq(
            "CHK-SMU-MEMINIT-RESTORED with the input low again a cold reset starts the sweep",
            (restored, enable_seen, writes_after > writes_before),
            (0, 1, True),
            evidence="CHK-SMU-MEMINIT-RESTORED",
        )
