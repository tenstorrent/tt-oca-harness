# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RESET_CTRL keeps a held core across a watchdog warm reset.

`clk_rst.adoc` (SMC Reset Distribution) states that the CPU control registers,
"including `RESET_CTRL`, `RESET_VECTOR` and `WDT_TIMEOUT`, are on the primary
reset and keep their values across a warm reset", that the warm-domain flops
"register the core and uncore reset requests from `RESET_CTRL`, so a warm
reset holds the cores and uncore in reset, and once it releases they follow
`RESET_CTRL` again".

Core 2 is held through `RESET_CTRL` in force mode and confirmed on
`tb_cpu_core_resets_n`. The warm reset is then entered through the SEP
watchdog reset input, which `smc_reset_ctrl.sv` folds into the warm reset;
while it is asserted every core and the uncore read in reset. After its release
`RESET_CTRL` reads the held word, cores 0, 1 and 3 and the uncore come back
released, core 2 stays held through a sampled window, and a release write
brings it out.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CHK = "CHK-RESET-CTRL-SURVIVES-WARM"

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
CORE = 2
CORE_N = cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{CORE}_RESET_N_N0_SCAN_bm")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_LEVEL_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
TIMED_OUT = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")
FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM

LEVEL_BOUND = 256
WARM_ASSERT_BOUND = 300
WARM_RELEASE_BOUND = 20_000
WARM_HOLD_CYCLES = 64
HELD_WINDOW_CYCLES = 64


class smc_reset_ctrl_survives_warm_test_seq(SmcCsrSeq):
    """Hold core 2 through RESET_CTRL, pulse the SEP watchdog warm reset, read RESET_CTRL back."""

    def __init__(self, name: str = "smc_reset_ctrl_survives_warm_test_seq") -> None:
        super().__init__(name)
        self.passed = False

    @staticmethod
    def _val(sig, what: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{what} is not resolvable: {value}"
        return int(value)

    async def _await(self, sig, what: str, want: int, bound: int) -> int:
        for n in range(bound):
            if self._val(sig, what) == want:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{what} did not read 0x{want:x} within {bound} clk_smc_i rises; last "
            f"0x{self._val(sig, what):x}"
        )

    async def _hold(self, sig, what: str, want: int, cycles: int, label: str) -> None:
        for n in range(cycles):
            await RisingEdge(cocotb.top.clk_smc_i)
            got = self._val(sig, what)
            assert got == want, f"{label}: {what} read 0x{got:x} at cycle {n}, want 0x{want:x}"

    async def body(self) -> None:
        dut = cocotb.top
        cores = dut.tb_cpu_core_resets_n
        uncore = dut.tb_cpu_uncore_reset_n
        warm = dut.tb_rst_warm_smc_clk_n
        await self.wait_fuse_sense_done()
        assert self._val(dut.tb_sep_wdt_reset_n, "tb_sep_wdt_reset_n") == 1, (
            "SEP WDT reset input not idle high"
        )
        ctrl_idle = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout_idle = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        assert ctrl_idle & UNCORE_N and ctrl_idle & CORE_LEVEL_N == CORE_LEVEL_N, (
            f"RESET_CTRL 0x{ctrl_idle:x}: the uncore and every core are expected released at idle"
        )
        assert not timeout_idle & APPLIED, (
            f"RESET_TIMEOUT 0x{timeout_idle:x}: a reset is already applied"
        )
        await self._await(cores, "tb_cpu_core_resets_n", CORE_LEVEL_N, LEVEL_BOUND)

        # S1: core 2 held through RESET_CTRL.
        held = ctrl_idle & ~CORE_N
        others = CORE_LEVEL_N & ~CORE_N
        await self.csr_write("TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("CORE_HOLD", RESET_CTRL, held, length=8)
        await self.csr_read("CORE_HOLD_RB", RESET_CTRL, length=8, expected=held)
        s1 = await self._await(cores, "tb_cpu_core_resets_n", others, LEVEL_BOUND)

        # S2: warm reset through the SEP watchdog reset input.
        dut.tb_sep_wdt_reset_n.value = 0
        fall = await self._await(warm, "tb_rst_warm_smc_clk_n", 0, WARM_ASSERT_BOUND)
        all_low = await self._await(cores, "tb_cpu_core_resets_n", 0, 8)
        await self._await(uncore, "tb_cpu_uncore_reset_n", 0, 8)
        await self._hold(cores, "tb_cpu_core_resets_n", 0, WARM_HOLD_CYCLES, "S2_WARM")
        assert self._val(warm, "tb_rst_warm_smc_clk_n") == 0, "warm reset released inside the hold"
        dut.tb_sep_wdt_reset_n.value = 1
        rise = await self._await(warm, "tb_rst_warm_smc_clk_n", 1, WARM_RELEASE_BOUND)

        # S3: after the release the resets follow RESET_CTRL again.
        back = await self._await(cores, "tb_cpu_core_resets_n", others, LEVEL_BOUND)
        await self._await(uncore, "tb_cpu_uncore_reset_n", 1, LEVEL_BOUND)
        ctrl_after = await self.csr_read("CORE_HOLD_AFTER_WARM", RESET_CTRL, length=8)
        timeout_after = await self.csr_read("TIMEOUT_AFTER_WARM", RESET_TIMEOUT, length=8)
        assert ctrl_after == held and self._val(cores, "tb_cpu_core_resets_n") == others, (
            f"{CHK} FAIL: after the warm reset RESET_CTRL reads 0x{ctrl_after:x} (held word "
            f"0x{held:x}) and tb_cpu_core_resets_n 0x{self._val(cores, 'cores'):x} "
            f"(want 0x{others:x}, core {CORE} still held)"
        )
        assert timeout_after & ~(APPLIED | TIMED_OUT) == FORCE_AFTER_32, (
            f"RESET_TIMEOUT reads 0x{timeout_after:x} after the warm reset, programmed "
            f"0x{FORCE_AFTER_32:x}"
        )
        await self._hold(cores, "tb_cpu_core_resets_n", others, HELD_WINDOW_CYCLES, "S3_HELD")

        # S4: the release write brings core 2 out.
        await self.csr_write("CORE_RELEASE", RESET_CTRL, ctrl_idle, length=8)
        s4 = await self._await(cores, "tb_cpu_core_resets_n", CORE_LEVEL_N, LEVEL_BOUND)
        await self.csr_read("RESET_CTRL_RELEASED_RB", RESET_CTRL, length=8, expected=ctrl_idle)
        cocotb.log.info(
            "%s PASS: RESET_CTRL 0x%x held core %d (tb_cpu_core_resets_n 0x%x after %d rises); "
            "the SEP WDT reset input took rst_warm_smc_clk_n low after %d rises, every core and "
            "the uncore low after %d more, held %d cycles, released after %d rises; RESET_CTRL "
            "read 0x%x and RESET_TIMEOUT 0x%x after it, cores back to 0x%x after %d rises and "
            "held there for %d cycles; the release write brought every core out after %d rises",
            CHK,
            held,
            CORE,
            others,
            s1,
            fall,
            all_low,
            WARM_HOLD_CYCLES,
            rise,
            ctrl_after,
            timeout_after,
            others,
            back,
            HELD_WINDOW_CYCLES,
            s4,
        )
        self.passed = True

        await self.csr_write("TIMEOUT_RESTORE", RESET_TIMEOUT, timeout_idle, length=8)
        await self.csr_read("TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout_idle)
