# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-1 / P2-7: ECC SBE/DBE inject hooks on scratch bank0.

DEFENDS: with inject armed, a real scratch bank0 read advances
tb_cpu_ecc_inject_fire_count via DUT cpu_scratch0_inject_fire; clearing inject
holds that counter while further scratch reads are still arriving. The claim is
the contrast between those two halves -- the hold alone is true for every DUT
state, because both inject pins are TB inputs and both are 0.
DOES NOT DEFEND: Rocket ECC syndrome CSR / precise RAS recovery FW policy, nor
any DUT SECDED behaviour -- the hook counts qualifying reads and corrupts no
data.
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

VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")

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
                    "%s fire_count %d -> %d after %d cycles (DUT scratch0_inject_fire path)",
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
        raise AssertionError(f"TIMEOUT SBE: no DUT fire within {_FIRE_BOUND_CYCLES} cycles")

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

        # SBE + recovery in one boot window: clear inject on first fire while
        # the I$ fill is still in flight, then require more scratch reads with
        # fire_count held (recovery).
        dut.tb_cpu_ecc_inject_sbe.value = 1
        await RisingEdge(clk)
        clearer = cocotb.start_soon(self._clear_sbe_on_first_fire(base))
        if _hold_cpu_boot_plusarg():
            boot_task = cocotb.start_soon(_release_held_cpu_boot(self, CPU_RESET_VECTOR_SCRATCH))
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
        #
        # `fire_count` is incremented by
        # models/smc_cpu_mem_dv.sv:scratch0_inject_fire_q, whose enable term is
        #   scratch_ram_req_i[0].en && !wmode && (ecc_inject_sbe_i || ecc_inject_dbe_i)
        # -- both inject pins are TB inputs and both are 0 here, so
        # `mid_after == mid` alone holds for every DUT state. The claim is the
        # CONTRAST across the two halves of this run, on the same counter:
        #   armed   (inject=1) -> the counter advanced; _clear_sbe_on_first_fire
        #                         returns only once fire_count > baseline and
        #                         raises on expiry.
        #   cleared (inject=0) -> the counter holds while further scratch reads
        #                         arrive; _wait_scratch_reads_gt raises if they
        #                         stop.
        # Both counts are carried in the token below.
        #
        # Scope: this proves the injection hook is gated by its enable pins and
        # that scratch traffic survives the clear. It does not prove Rocket
        # SECDED behaviour -- no corrupted data is forced onto any macro
        # response in this bench (CHK-ECC-INJECT-NO-DUT-SECDED says the same).
        await self._wait_scratch_reads_gt(scratch_hold, label="RECOVERY")
        await ClockCycles(clk, 8)
        mid_after = int(dut.tb_cpu_ecc_inject_fire_count.value)
        scratch_after = int(dut.tb_cpu_scratch_read_count.value)
        assert mid_after == mid, (
            f"inject-clear recovery failed during I$ fill: fire_count {mid} -> "
            f"{mid_after} with both inject pins 0 (armed half advanced "
            f"{base} -> {sbe}; scratch_reads {scratch_hold} -> {scratch_after})"
        )
        cocotb.log.info(
            "CHK-ECC-INJECT-RECOVERY: armed fire_count %d -> %d, then with "
            "inject cleared held at %d across scratch_reads %d -> %d "
            "(hook gating, not DUT SECDED)",
            base,
            sbe,
            mid_after,
            scratch_hold,
            scratch_after,
        )

        # Arm DBE while the first-boot I$ fill is in flight: once the boot
        # fetch has completed, a later pulse_core_reset produces no fresh bank0
        # traffic.
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

        dut.tb_cpu_ecc_inject_dbe.value = 0
        # The baseline for the recovery wait is taken AFTER `boot_task`
        # completes. A baseline sampled before the CPU has fetched anything is
        # already exceeded by the time the wait starts, so the wait would return
        # on its first cycle and could not fail ([TIMEOUT-MUST-FAIL] /
        # [NO-ALWAYS-PASS-CHECKER]).
        await boot_task
        # The CPU does not re-fetch from scratch bank0 once the boot fetch has
        # completed, so the recovery property -- further scratch traffic with
        # the inject cleared must not score -- is proven only by the `RECOVERY`
        # leg above ([NO-ALWAYS-PASS-CHECKER]).

        await self.wait_fuse_sense_done()
        await self.csr_read("VERSION_LO", VERSION_LO)

        await ClockCycles(clk, 2)
        cocotb.log.info(
            "CHK-ECC-INJECT: TB inject fire_count SBE %d->%d recovery_hold=%d DBE %d->%d",
            base,
            sbe,
            mid,
            mid,
            dbe,
        )
        cocotb.log.info(
            "CHK-ECC-INJECT-NO-DUT-SECDED: this testcase makes NO claim about the\n"
            "DUT's own SECDED detector. `tb_cpu_ecc_inject_sbe/dbe` do not\n"
            "corrupt any data: smc_cpu_mem_dv.sv:70-78 only counts reads issued\n"
            "while an inject is armed, so `cluster_ded_o` cannot fire from this\n"
            "path and asserting on it would be a check that can never pass.\n"
            "What IS proven here is the inject-and-recover path on the TB hook.\n"
            "The DUT SECDED property is proven by corrupting the stored codeword\n"
            "through `tb_cpu_ecc_poke_*` -- see smc_ecc_codeword_corrupt_test_seq."
        )
