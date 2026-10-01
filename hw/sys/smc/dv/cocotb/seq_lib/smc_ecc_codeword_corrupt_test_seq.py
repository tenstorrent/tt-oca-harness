# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-1 / P2-7: a corrupted scratch ECC codeword reaching the CPU's ECC logic.

Scratch bank0 stores the full 72-bit codeword (SMC_4CORE_SCRATCH_RAM_DATA_WIDTH
= 72), so XORing bits into the macro array is a real fault rather than a faked
read response -- the same posture the SEP testbench uses when it writes
codewords into its macro arrays directly. The poke lands before boot release so
the corrupted word is read by the reset-vector fetch itself; poking after the
line is cached is not observed.

DEFENDS: one flipped bit is benign -- the CPU reads the poked bank and cluster
DED stays low across a quiet window. Two flipped bits in the same word are not,
and the CPU raises cluster_ded_o (smc_4core_cpu.sv flops
|{io_errors_uncorrectable_valid, uncorrectable_2} into it). The contrast across
the two vehicles is the evidence: same location, benign at one bit and fatal at
two.
DOES NOT DEFEND: that the single-bit fault was actually corrected. No
correctable-error counter is exposed at this boundary, only the absence of DED.
Rocket ECC syndrome CSRs and RAS recovery policy are out of scope.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_cpu_vip_utils import (
    CPU_RESET_VECTOR_SCRATCH,
    _hold_cpu_boot_plusarg,
    _release_held_cpu_boot,
)
from .smc_csr_seq_utils import SmcCsrSeq

# Bank0 entry 0 is the first 8 bytes of the scratch image -- offset 0 is where
# every field of the smc_scratch_map_pkg decode reads zero -- so the
# reset-vector fetch reads it.
_POKE_ENTRY = 0
_SCRATCH_BOUND_CYCLES = 400_000
_DED_BOUND_CYCLES = 400_000
# How long DED must stay clear before a single-bit fault is called benign.
_DED_QUIET_CYCLES = 20_000


class smc_ecc_codeword_corrupt_test_seq(SmcCsrSeq):
    """Corrupt one scratch codeword before boot and score the CPU's reaction.

    `poke_mask` is XORed into bank0 entry 0: one set bit is a correctable
    fault, two are not. `expect_ded` says which outcome this vehicle scores.
    """

    def __init__(self, name: str, *, poke_mask: int, expect_ded: bool) -> None:
        super().__init__(name)
        self.poke_mask = poke_mask
        self.expect_ded = expect_ded

    async def _poke(self, mask: int) -> None:
        """Pulse one XOR of `mask` into bank0 entry _POKE_ENTRY."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        dut.tb_cpu_ecc_poke_entry.value = _POKE_ENTRY
        dut.tb_cpu_ecc_poke_mask.value = mask
        await RisingEdge(clk)
        dut.tb_cpu_ecc_poke_en.value = 1
        await ClockCycles(clk, 2)
        dut.tb_cpu_ecc_poke_en.value = 0
        await ClockCycles(clk, 2)

    async def _wait_scratch_reads_gt(self, baseline: int) -> int:
        """Bounded wait for real scratch traffic, so the poke is not vacuous."""
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(_SCRATCH_BOUND_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_cpu_scratch_read_count.value.is_resolvable:
                continue
            cur = int(dut.tb_cpu_scratch_read_count.value)
            if cur > baseline:
                cocotb.log.info("scratch_reads %d -> %d after %d cycles", baseline, cur, i + 1)
                return cur
        raise AssertionError(
            f"TIMEOUT: scratch_reads stuck at {baseline} for "
            f"{_SCRATCH_BOUND_CYCLES} cycles (CPU never read the poked bank)"
        )

    async def _wait_ded(self) -> int:
        dut = cocotb.top
        clk = dut.clk_smc_i
        for i in range(_DED_BOUND_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_cluster_ded_seen.value.is_resolvable:
                continue
            if int(dut.tb_cluster_ded_seen.value):
                return i + 1
        raise AssertionError(
            f"TIMEOUT DED: cluster_ded never asserted within "
            f"{_DED_BOUND_CYCLES} cycles of a 2-bit codeword corruption"
        )

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i

        if "smc_scratch_ram_hex" not in cocotb.plusargs:
            raise AssertionError(
                "smc_ecc_codeword_corrupt vehicles require +smc_scratch_ram_hex "
                "(a real codeword image to corrupt)"
            )

        dut.tb_cpu_ecc_poke_en.value = 0
        dut.tb_cpu_ecc_poke_entry.value = 0
        dut.tb_cpu_ecc_poke_mask.value = 0
        # This vehicle corrupts the stored codeword; the rdata-side inject hook
        # scored by smc_ecc_fault_inject_test stays off.
        dut.tb_cpu_ecc_inject_sbe.value = 0
        dut.tb_cpu_ecc_inject_dbe.value = 0
        await ClockCycles(clk, 2)

        assert int(dut.tb_cluster_ded_seen.value) == 0, (
            "cluster_ded already set before any corruption"
        )

        # Corrupt before the reset-vector fetch, so the first read sees it.
        scratch_base = int(dut.tb_cpu_scratch_read_count.value)
        await self._poke(self.poke_mask)
        if _hold_cpu_boot_plusarg():
            await _release_held_cpu_boot(self, CPU_RESET_VECTOR_SCRATCH)

        bits = bin(self.poke_mask).count("1")
        if self.expect_ded:
            ded_cycles = await self._wait_ded()
            reads = int(dut.tb_cpu_scratch_read_count.value)
            assert reads > scratch_base, (
                "cluster_ded asserted without any scratch read -- the DED did "
                "not come from the poked codeword"
            )
            cocotb.log.info(
                "CHK-ECC-CODEWORD-DED: bank0 entry %d ^= %d bits (mask 0x%x); "
                "scratch_reads %d->%d and cluster_ded asserted after %d cycles",
                _POKE_ENTRY,
                bits,
                self.poke_mask,
                scratch_base,
                reads,
                ded_cycles,
            )
        else:
            reads = await self._wait_scratch_reads_gt(scratch_base)
            await ClockCycles(clk, _DED_QUIET_CYCLES)
            ded = int(dut.tb_cluster_ded_seen.value)
            assert ded == 0, (
                f"single-bit codeword fault raised cluster_ded after "
                f"{_DED_QUIET_CYCLES} cycles; expected it to be correctable"
            )
            cocotb.log.info(
                "CHK-ECC-CODEWORD-SEC: bank0 entry %d ^= %d bit (mask 0x%x); "
                "scratch_reads %d->%d with cluster_ded held at 0 for %d cycles",
                _POKE_ENTRY,
                bits,
                self.poke_mask,
                scratch_base,
                reads,
                _DED_QUIET_CYCLES,
            )
