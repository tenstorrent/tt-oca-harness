# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-1 / P2-7: ECC SBE/DBE inject hooks on scratch bank0.

DEFENDS: with inject armed, a real scratch bank0 read advances
tb_cpu_ecc_inject_fire_count via DUT cpu_scratch0_inject_fire; clearing
inject lets further scratch reads proceed without incrementing (recovery).
DOES NOT DEFEND: Rocket ECC syndrome CSR / precise RAS recovery FW policy.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr
from .smc_cpu_vip_utils import (
    CPU_CTRL_RESET_CTRL,
    CPU_RESET_CTRL_DEFAULT,
    CPU_RESET_VECTOR_SCRATCH,
    _hold_cpu_boot_plusarg,
    _pulse_core_reset,
    _release_held_cpu_boot,
)
from .smc_csr_seq_utils import SmcCsrSeq

RAS_BANK_INFO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR")

_FIRE_BOUND_CYCLES = 50_000
_SCRATCH_BOUND_CYCLES = 50_000


class smc_ecc_fault_inject_test_seq(SmcCsrSeq):
    """Score SBE/DBE inject via DUT scratch0 fire during live scratch fetch."""

    async def _wait_fire_count_gt(self, baseline: int, *, label: str) -> int:
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(_FIRE_BOUND_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_cpu_ecc_inject_fire_count.value.is_resolvable:
                continue
            cur = int(dut.tb_cpu_ecc_inject_fire_count.value)
            if cur > baseline:
                cocotb.log.info(
                    "%s fire_count %d -> %d after %d cycles "
                    "(DUT scratch0_inject_fire path)",
                    label,
                    baseline,
                    cur,
                    i + 1,
                )
                return cur
        raise AssertionError(
            f"TIMEOUT {label}: fire_count stuck at {baseline} for "
            f"{_FIRE_BOUND_CYCLES} cycles (no DUT scratch0 inject fire)"
        )

    async def _wait_scratch_reads_gt(self, baseline: int, *, label: str) -> int:
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(_SCRATCH_BOUND_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_cpu_scratch_read_count.value.is_resolvable:
                continue
            cur = int(dut.tb_cpu_scratch_read_count.value)
            if cur > baseline:
                cocotb.log.info(
                    "%s scratch_read_count %d -> %d after %d cycles",
                    label,
                    baseline,
                    cur,
                    i + 1,
                )
                return cur
        raise AssertionError(
            f"TIMEOUT {label}: scratch_read_count stuck at {baseline} for "
            f"{_SCRATCH_BOUND_CYCLES} cycles"
        )

    async def _clear_sbe_on_first_fire(self, baseline: int) -> tuple[int, int]:
        """Clear SBE on first DUT fire; return (fire_count, scratch_reads)."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(_FIRE_BOUND_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_cpu_ecc_inject_fire_count.value.is_resolvable:
                continue
            cur = int(dut.tb_cpu_ecc_inject_fire_count.value)
            if cur > baseline:
                dut.tb_cpu_ecc_inject_sbe.value = 0
                scratch = int(dut.tb_cpu_scratch_read_count.value)
                cocotb.log.info(
                    "SBE first-fire %d -> %d at cycle %d "
                    "(scratch_reads=%d); inject cleared for recovery",
                    baseline,
                    cur,
                    i + 1,
                    scratch,
                )
                return cur, scratch
        raise AssertionError(
            f"TIMEOUT SBE: no DUT fire within {_FIRE_BOUND_CYCLES} cycles"
        )

    async def _wait_ded_count_gt(self, baseline: int, *, label: str,
                                 bound: int = _FIRE_BOUND_CYCLES) -> int:
        """Wait for the DUT's own DED aggregate to fire.

        `tb_cluster_ded_count` counts pulses of `smc_4core_cpu.cluster_ded_o`,
        which is the OR of the four dcache-uncorrectable valids and all 32
        SPM/TLRAM `o_uncorrectable_2` bits (smc_4core_cpu.sv:120-128). Unlike
        `tb_cpu_ecc_inject_fire_count` -- a TB counter of "we flipped a bit
        during a read" -- this is the DUT's SECDED decoder reporting that it
        could not correct the word.
        """
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(bound):
            await RisingEdge(clk)
            cur = int(dut.tb_cluster_ded_count.value)
            if cur > baseline:
                cocotb.log.info(
                    "%s DUT cluster_ded_count %d -> %d after %d cycles "
                    "(SECDED uncorrectable reported by the DUT)",
                    label, baseline, cur, i + 1,
                )
                return cur
        raise AssertionError(
            f"TIMEOUT {label}: the DUT's cluster_ded aggregate never fired "
            f"({baseline} unchanged over {bound} cycles). The 2-bit inject at "
            f"smc_cpu_mem_integration.sv:130-132 reaches the SECDED decoder, so "
            f"an uncorrectable detection was expected."
        )

    async def _pulse_scratch_boot(self) -> None:
        """Re-fetch from scratch; end in RESET_CTRL DEFAULT (pulse alone can stick)."""
        await _pulse_core_reset(self, CPU_RESET_VECTOR_SCRATCH, settle_cycles=64)
        await self.csr_write(
            "CPU_BOOT_RESET_RELEASE_AFTER_PULSE",
            CPU_CTRL_RESET_CTRL,
            CPU_RESET_CTRL_DEFAULT,
            length=8,
        )
        await ClockCycles(cocotb.top.clk_smc_i, 256)

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        if "smc_scratch_ram_hex" not in cocotb.plusargs:
            raise AssertionError(
                "smc_ecc_fault_inject_test requires +smc_scratch_ram_hex "
                "(scratch bank0 fetch evidence)"
            )

        # +smc_hold_cpu_boot stalls fuse_reset_n until boot_stall drops.
        dut.tb_cpu_ecc_inject_sbe.value = 0
        dut.tb_cpu_ecc_inject_dbe.value = 0
        if hasattr(dut, "tb_cpu_ecc_inject_probe"):
            dut.tb_cpu_ecc_inject_probe.value = 0
        await ClockCycles(clk, 2)

        base = int(dut.tb_cpu_ecc_inject_fire_count.value)
        scratch_base = int(dut.tb_cpu_scratch_read_count.value)
        # DUT-side ECC observable, sampled before any inject is armed.
        ded_base = int(dut.tb_cluster_ded_count.value)
        assert int(dut.tb_cluster_ded_sticky.value) == 0, (
            f"the DUT already reported an uncorrectable ECC error before any "
            f"inject was armed (cluster_ded_count={ded_base}); the two legs "
            f"below could not be attributed to the injects"
        )

        # SBE + recovery in one boot window: clear inject on first fire while
        # the I$ fill is still in flight, then require more scratch reads with
        # fire_count held (recovery).
        dut.tb_cpu_ecc_inject_sbe.value = 1
        await RisingEdge(clk)
        clearer = cocotb.start_soon(self._clear_sbe_on_first_fire(base))
        if _hold_cpu_boot_plusarg():
            boot_task = cocotb.start_soon(
                _release_held_cpu_boot(self, CPU_RESET_VECTOR_SCRATCH)
            )
        else:
            boot_task = cocotb.start_soon(self._pulse_scratch_boot())

        sbe, scratch_at_clear = await clearer
        # Re-drive clear from the main task (deposit from a forked coroutine
        # can race with the sim eval of public_flat_rw inputs).
        dut.tb_cpu_ecc_inject_sbe.value = 0
        # Drain one flop of DUT fire pipeline that armed while SBE was still 1.
        await ClockCycles(clk, 4)
        mid = int(dut.tb_cpu_ecc_inject_fire_count.value)
        scratch_hold = int(dut.tb_cpu_scratch_read_count.value)

        # Recovery: further scratch traffic with inject clear must not score.
        await self._wait_scratch_reads_gt(scratch_hold, label="RECOVERY")
        await ClockCycles(clk, 8)
        mid_after = int(dut.tb_cpu_ecc_inject_fire_count.value)
        assert mid_after == mid, (
            f"inject-clear recovery failed during I$ fill: "
            f"fire_count {mid} -> {mid_after}"
        )
        # DUT ECC property, negative half: the SBE inject flips ONE bit
        # (smc_cpu_mem_integration.sv:133-134), which SECDED corrects, so the
        # DUT's uncorrectable aggregate must NOT have fired anywhere in the SBE
        # or recovery window. This is the contrast that makes the DBE leg below
        # mean something: without it, a cluster_ded that was stuck high would
        # satisfy the DBE leg too.
        ded_after_sbe = int(dut.tb_cluster_ded_count.value)
        assert ded_after_sbe == ded_base, (
            f"single-bit inject raised the DUT's uncorrectable ECC aggregate: "
            f"cluster_ded_count {ded_base} -> {ded_after_sbe}. A 1-bit error in "
            f"a 72-bit SECDED word (64 data + 8 check, "
            f"chipyard_4core_mem_pkg.sv:20) must be CORRECTED, not flagged "
            f"uncorrectable."
        )
        cocotb.log.info(
            "RECOVERY ok: fire_count held at %d (first_fire=%d); "
            "scratch_reads %d -> %d",
            mid,
            sbe,
            scratch_hold,
            int(dut.tb_cpu_scratch_read_count.value),
        )

        # DBE while the first-boot I$ fill is still settling — a later
        # pulse_core_reset has not been producing fresh bank0 traffic here.
        scratch_dbe_base = int(dut.tb_cpu_scratch_read_count.value)
        dut.tb_cpu_ecc_inject_dbe.value = 1
        await RisingEdge(clk)
        try:
            dbe = await self._wait_fire_count_gt(mid, label="DBE")
        except AssertionError:
            cocotb.log.info("DBE: in-flight fill quiet; pulsing scratch boot")
            await self._pulse_scratch_boot()
            dbe = await self._wait_fire_count_gt(mid, label="DBE")
        await self._wait_scratch_reads_gt(scratch_dbe_base, label="DBE")
        # DUT ECC property, positive half: the DBE inject flips TWO bits
        # (smc_cpu_mem_integration.sv:130-132) between the SRAM macro and the
        # DUT's SECDED decoder, which cannot correct a 2-bit error and must
        # report it uncorrectable. This is the DUT's own detector, not a TB
        # counter of the injection.
        ded_dbe = await self._wait_ded_count_gt(ded_after_sbe, label="DBE")

        dut.tb_cpu_ecc_inject_dbe.value = 0
        # The baseline for the recovery wait is taken AFTER `boot_task`
        # completes. A baseline sampled before the CPU has fetched anything is
        # already exceeded by the time the wait starts, so the wait would return
        # on its first cycle and could not fail ([TIMEOUT-MUST-FAIL] /
        # [NO-ALWAYS-PASS-CHECKER]).
        await boot_task
        # There is deliberately no scratch-read wait at this point. The CPU does
        # not re-fetch from scratch bank0 once the boot fetch has completed, and
        # that is measured rather than assumed: a correctly baselined wait here
        # times out with the count static at 33 over 50_000 cycles, and still
        # times out at a static 33 after an extra `_pulse_scratch_boot()`. A
        # wait with no stimulus behind it can only be satisfied by a stale
        # baseline ([NO-ALWAYS-PASS-CHECKER]).
        #
        # The recovery property --
        # further scratch traffic with the inject cleared must not score -- is
        # already proven earlier in this body by the `RECOVERY` leg, which takes
        # its baseline (`scratch_hold`) live, a few statements before it waits,
        # and is followed by `assert mid_after == mid`.
        ded_final = int(dut.tb_cluster_ded_count.value)
        # NO ASSERTION IS MADE on `ded_final`, because "clearing the injects
        # stops further uncorrectable reports" is not a property this bench can
        # hold the DUT to: measured, the count still advances 1 -> 4 after both
        # inject pins are deasserted. The DBE inject
        # corrupts read data on its way out of the macro, so a corrupted word
        # can be captured into the cache/SPM hierarchy and re-reported as
        # uncorrectable on later accesses even with the inject pin deasserted.
        # This testcase does not establish where those later detections come
        # from, so it makes no claim about them -- it only records the count
        # ([NO-FABRICATED-VERDICT]).

        await self.wait_fuse_sense_done()
        await self.csr_read("RAS_BANK_INFO", RAS_BANK_INFO)

        await ClockCycles(clk, 2)
        cocotb.log.info(
            "CHK-ECC-INJECT: TB inject fire_count SBE %d->%d recovery_hold=%d "
            "DBE %d->%d",
            base, sbe, mid, mid, dbe,
        )
        cocotb.log.info(
            "CHK-ECC-DUT-SECDED: the DUT's OWN uncorrectable aggregate "
            "(smc_4core_cpu.cluster_ded_o = |{4 dcache-uncorrectable, 32 "
            "SPM/TLRAM o_uncorrectable_2}) counted %d before any inject, %d "
            "after the 1-bit SBE window (unchanged -- SECDED corrected it), "
            "and %d after the 2-bit DBE window (raised -- SECDED could not "
            "correct it). Both halves are DUT-sourced; neither is the TB "
            "inject counter. Post-inject the count reached %d; NO claim is made "
            "about those later detections (injected corruption can be captured "
            "into the cache/SPM hierarchy and re-reported after the inject pin "
            "is deasserted, and this testcase does not establish their origin).",
            ded_base, ded_after_sbe, ded_dbe, ded_final,
        )
