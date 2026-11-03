# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The uncore reset and the warm reset return the CLINT and watchdog 0 to their reset state.

`clk_rst.adoc` (SMC Reset Distribution) states that `cluster_uncore_reset_n`
"resets the uncore of the generated cluster: its buses, coherence manager,
CLINT, PLIC, boot ROM interface, the bus side of the debug module and the four
watchdogs", and (Reset Domains) that the warm reset "drives CPU core/uncore
reset control, including the cluster's interrupt and timer logic".

With `REGION_SIZE` widened so the CLINT and PLIC windows decode, non-reset
values are programmed over SEP_IN into `MSIP[0]`, `MTIME`,
`MTIMECMP[0]`, `PRIORITY[1]`, and watchdog 0's `CTRL`, `COUNT` and `CMP`, and
read back, so every path is live before the reset. The uncore reset is then
pulsed through `RESET_CTRL.uncore_reset_n_n0_scan` in force mode, and in a
second pass the warm reset is pulsed through the SEP watchdog reset input.
Every core is held through `RESET_CTRL` before the first programming and
released only after the last readback, so no core runs ROM code between a
reset and the reads that grade it. After each release `MSIP[0]` reads its
`clint.rdl` reset word, `MTIME` reads
its reset word plus at most the ticks the `clk_smc_i` cycles since the release
allow (`clint.h`: one every 1000 cbus cycles), and the watchdog registers read
their `wdt.rdl` reset words.

`MTIMECMP` and `PRIORITY` are registers the generated CLINT and PLIC never
reset (software initialises them), so their post-reset values are recorded
and not compared; the PLIC has no software-visible register with a reset, so
the PLIC half of the sentence is not graded here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    _REPO,
    _WDT_H,
    REGION_SIZE_RESET,
    cpu_ctrl_u32,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
    wdt_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq

CHK_UNCORE = "CHK-UNCORE-RESET-CLEARS-CLINT-WDT"
CHK_WARM = "CHK-WARM-RESET-CLEARS-CLINT-WDT"

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_LEVEL_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM

REGION_SIZE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
REGION_SIZE_256M = 0x1000_0000
MSIP0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MSIP_BASE_ADDR", 0)
MTIME = smc_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIME_BASE_ADDR")
MTIMECMP0 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_CLINT_MTIMECMP_BASE_ADDR", 0)
PRIORITY1 = smc_indexed_addr("SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY_BASE_ADDR", 1)
WDT0_KEY = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
WDT0_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR")
WDT0_COUNT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_COUNT_BASE_ADDR")
WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
_CLINT_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "clint.h"
MSIP_RESET = reg_reset_word(_CLINT_H, "CLINT", "MSIP")
MTIME_RESET = reg_reset_word(_CLINT_H, "CLINT", "MTIME")
# clint.h: MTIME "increments by one every 1000 CPU-cluster cbus clock cycles".
MTIME_TICK_CYCLES = 1000
MTIME_TICK_ALLOWANCE = 2
WDT_MAGIC_KEY = 0x51F15E
WDT_CTRL_RESET = reg_reset_word(_WDT_H, "WDT", "CTRL")
WDT_COUNT_RESET = reg_reset_word(_WDT_H, "WDT", "COUNT")
WDT_CMP_RESET = reg_reset_word(_WDT_H, "WDT", "CMP")
# Scale field only: the count enables stay clear, so COUNT holds its written value.
WDT_CTRL_PATTERN = wdt_u32("WDT__CTRL__WDOGSCALE_bm")
WDT_COUNT_PATTERN = 0x0010_0000
WDT_CMP_PATTERN = wdt_u32("WDT__CMP__WDOGCMP0_bm") & 0x7FFF
MTIME_PATTERN = 0x0000_1000_0000_0000
MTIMECMP_PATTERN = 0x0123_4567_89AB_CDEF
PRIORITY_PATTERN = 5

_LEVEL_BOUND = 256
_WARM_ASSERT_BOUND = 300
_WARM_RELEASE_BOUND = 20_000
_WARM_HOLD_CYCLES = 64


class smc_uncore_warm_reset_clears_timers_test_seq(SmcCsrSeq):
    """Program the CLINT, PLIC and watchdog 0, pulse the uncore reset, then the warm reset."""

    def __init__(self, name: str = "smc_uncore_warm_reset_clears_timers_test_seq") -> None:
        super().__init__(name)
        self.passes: list[str] = []
        self.released_ps = 0

    async def _wdt_wr(self, label: str, addr: int, data: int) -> None:
        await self.csr_write(f"WDT0_KEY_{label}", WDT0_KEY, WDT_MAGIC_KEY)
        await self.csr_write(f"WDT0_{label}", addr, data)

    async def _program(self, tag: str) -> str:
        """Program the seven registers and read each back; return the two counting readbacks."""
        assert MSIP_RESET != 1 and MTIME_RESET < MTIME_PATTERN, (
            f"MSIP reset 0x{MSIP_RESET:x} or MTIME reset 0x{MTIME_RESET:x} overlaps its pattern"
        )
        await self.csr_write(f"MSIP0_{tag}", MSIP0, 1)
        await self.csr_read(f"MSIP0_{tag}_RB", MSIP0, expected=1)
        await self.csr_write(f"MTIME_{tag}", MTIME, MTIME_PATTERN, length=8)
        mtime = await self.csr_read(f"MTIME_{tag}_RB", MTIME, length=8)
        assert MTIME_PATTERN <= mtime <= MTIME_PATTERN + MTIME_TICK_ALLOWANCE, (
            f"{tag}: MTIME reads 0x{mtime:x}, want 0x{MTIME_PATTERN:x} plus at most "
            f"{MTIME_TICK_ALLOWANCE} ticks"
        )
        await self.csr_write(f"MTIMECMP0_{tag}", MTIMECMP0, MTIMECMP_PATTERN, length=8)
        await self.csr_read(f"MTIMECMP0_{tag}_RB", MTIMECMP0, expected=MTIMECMP_PATTERN, length=8)
        await self.csr_write(f"PRIORITY1_{tag}", PRIORITY1, PRIORITY_PATTERN)
        await self.csr_read(f"PRIORITY1_{tag}_RB", PRIORITY1, expected=PRIORITY_PATTERN)
        await self._wdt_wr(f"CTRL_{tag}", WDT0_CTRL, WDT_CTRL_PATTERN)
        await self.csr_read(f"WDT0_CTRL_{tag}_RB", WDT0_CTRL, expected=WDT_CTRL_PATTERN)
        await self._wdt_wr(f"CMP_{tag}", WDT0_CMP, WDT_CMP_PATTERN)
        await self.csr_read(f"WDT0_CMP_{tag}_RB", WDT0_CMP, expected=WDT_CMP_PATTERN)
        await self._wdt_wr(f"COUNT_{tag}", WDT0_COUNT, WDT_COUNT_PATTERN)
        count = await self.csr_read(f"WDT0_COUNT_{tag}_RB", WDT0_COUNT)
        assert count >= WDT_COUNT_PATTERN, (
            f"{tag}: WDT0 COUNT reads 0x{count:x} below the written pattern"
        )
        assert (
            WDT_CTRL_PATTERN != WDT_CTRL_RESET
            and WDT_CMP_PATTERN != WDT_CMP_RESET
            and WDT_COUNT_PATTERN != WDT_COUNT_RESET
        ), "a programmed watchdog value equals its reset word, so the compare cannot fail"
        return f"MTIME read back 0x{mtime:x} and WDT0.COUNT 0x{count:x} before the reset"

    async def _readback(self, tag: str, released_ps: int) -> str:
        """Read the seven registers after the release observed at `released_ps`."""
        msip = await self.csr_read(f"MSIP0_{tag}_POST", MSIP0)
        mtime = await self.csr_read(f"MTIME_{tag}_POST", MTIME, length=8)
        elapsed = (int(get_sim_time("ps")) - released_ps) // int(self.cfg.smc_clk_period_ns * 1000)
        mtime_bound = MTIME_RESET + elapsed // MTIME_TICK_CYCLES + MTIME_TICK_ALLOWANCE
        mtimecmp = await self.csr_read(f"MTIMECMP0_{tag}_POST", MTIMECMP0, length=8)
        prio = await self.csr_read(f"PRIORITY1_{tag}_POST", PRIORITY1)
        ctrl = await self.csr_read(f"WDT0_CTRL_{tag}_POST", WDT0_CTRL)
        cmp_ = await self.csr_read(f"WDT0_CMP_{tag}_POST", WDT0_CMP)
        count = await self.csr_read(f"WDT0_COUNT_{tag}_POST", WDT0_COUNT)
        wrong = []
        if msip != MSIP_RESET:
            wrong.append(f"MSIP[0]=0x{msip:x} want 0x{MSIP_RESET:x}")
        if not MTIME_RESET <= mtime <= mtime_bound:
            wrong.append(
                f"MTIME=0x{mtime:x} outside 0x{MTIME_RESET:x}..0x{mtime_bound:x} "
                f"({elapsed} clk_smc_i cycles since the release)"
            )
        if ctrl != WDT_CTRL_RESET:
            wrong.append(f"WDT0.CTRL=0x{ctrl:x} want 0x{WDT_CTRL_RESET:x}")
        if cmp_ != WDT_CMP_RESET:
            wrong.append(f"WDT0.CMP=0x{cmp_:x} want 0x{WDT_CMP_RESET:x}")
        if count != WDT_COUNT_RESET:
            wrong.append(f"WDT0.COUNT=0x{count:x} want 0x{WDT_COUNT_RESET:x}")
        text = (
            f"MSIP[0]=0x{msip:x} (reset 0x{MSIP_RESET:x}) MTIME=0x{mtime:x} (reset "
            f"0x{MTIME_RESET:x}, at most 0x{mtime_bound:x} after {elapsed} cycles, programmed "
            f"0x{MTIME_PATTERN:x}) "
            f"WDT0.CTRL=0x{ctrl:x} WDT0.CMP=0x{cmp_:x} WDT0.COUNT=0x{count:x} "
            f"(reset words 0x{WDT_CTRL_RESET:x}/0x{WDT_CMP_RESET:x}/0x{WDT_COUNT_RESET:x}); "
            f"MTIMECMP[0]=0x{mtimecmp:x} and PRIORITY[1]=0x{prio:x} recorded, not compared"
        )
        assert not wrong, f"{tag}: {'; '.join(wrong)}; {text}"
        return text

    @staticmethod
    def _bit(sig, what: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{what} is not resolvable: {value}"
        return int(value)

    async def _await_level(self, sig, what: str, want: int, bound: int) -> int:
        for n in range(bound):
            if self._bit(sig, what) == want:
                return n
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{what} did not read {want} within {bound} clk_smc_i rises; last {self._bit(sig, what)}"
        )

    async def _uncore_pulse(self, held_cores: int) -> str:
        dut = cocotb.top
        await self.csr_write("UNCORE_HOLD", RESET_CTRL, held_cores & ~UNCORE_N, length=8)
        await self.csr_read("UNCORE_HOLD_RB", RESET_CTRL, length=8, expected=held_cores & ~UNCORE_N)
        low = await self._await_level(
            dut.tb_cpu_uncore_reset_n, "tb_cpu_uncore_reset_n", 0, _LEVEL_BOUND
        )
        await self.csr_write("UNCORE_RELEASE", RESET_CTRL, held_cores, length=8)
        high = await self._await_level(
            dut.tb_cpu_uncore_reset_n, "tb_cpu_uncore_reset_n", 1, _LEVEL_BOUND
        )
        self.released_ps = int(get_sim_time("ps"))
        cores = self._bit(dut.tb_cpu_core_resets_n, "tb_cpu_core_resets_n")
        assert cores == 0, f"tb_cpu_core_resets_n reads 0x{cores:x} after the uncore release"
        return (
            f"tb_cpu_uncore_reset_n read 0 after {low} rises of the uncore bit written 0 and 1 "
            f"after {high} rises of it written 1, every core still held"
        )

    async def _warm_pulse(self) -> str:
        dut = cocotb.top
        clk = dut.clk_smc_i
        assert self._bit(dut.tb_sep_wdt_reset_n, "tb_sep_wdt_reset_n") == 1, (
            "SEP WDT reset input not idle high"
        )
        dut.tb_sep_wdt_reset_n.value = 0
        fall = await self._await_level(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 0, _WARM_ASSERT_BOUND
        )
        uncore_low = await self._await_level(
            dut.tb_cpu_uncore_reset_n, "tb_cpu_uncore_reset_n", 0, 8
        )
        for _ in range(_WARM_HOLD_CYCLES):
            await RisingEdge(clk)
            assert self._bit(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n") == 0, (
                "warm reset released while the SEP WDT reset input is still low"
            )
        dut.tb_sep_wdt_reset_n.value = 1
        rise = await self._await_level(
            dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n", 1, _WARM_RELEASE_BOUND
        )
        high = await self._await_level(
            dut.tb_cpu_uncore_reset_n, "tb_cpu_uncore_reset_n", 1, _LEVEL_BOUND
        )
        self.released_ps = int(get_sim_time("ps"))
        cores = self._bit(dut.tb_cpu_core_resets_n, "tb_cpu_core_resets_n")
        assert cores == 0, f"tb_cpu_core_resets_n reads 0x{cores:x} after the warm release"
        return (
            f"rst_warm_smc_clk_n 0 after {fall} rises of the SEP WDT reset input falling "
            f"(tb_cpu_uncore_reset_n 0 after {uncore_low} more), held {_WARM_HOLD_CYCLES} cycles, "
            f"1 after {rise} rises of the input rising (uncore 1 after {high} rises, every core "
            f"still held)"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        assert ctrl & UNCORE_N and ctrl & CORE_LEVEL_N == CORE_LEVEL_N, (
            f"RESET_CTRL 0x{ctrl:x}: the uncore and every core are expected released at idle"
        )
        assert not timeout & APPLIED, f"RESET_TIMEOUT 0x{timeout:x}: a reset is already applied"
        await self.csr_write("TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("REGION_SIZE_256M", REGION_SIZE, REGION_SIZE_256M)
        await self.csr_read("REGION_SIZE_256M_RB", REGION_SIZE, expected=REGION_SIZE_256M)
        held_cores = ctrl & ~CORE_LEVEL_N
        await self.csr_write("CORES_HOLD", RESET_CTRL, held_cores, length=8)
        await self._await_level(dut.tb_cpu_core_resets_n, "tb_cpu_core_resets_n", 0, _LEVEL_BOUND)

        pre = await self._program("UNCORE")
        pulse = await self._uncore_pulse(held_cores)
        post = await self._readback("UNCORE", self.released_ps)
        cocotb.log.info("%s PASS: %s; %s; after the release %s", CHK_UNCORE, pre, pulse, post)
        self.passes.append(CHK_UNCORE)

        pre = await self._program("WARM")
        pulse = await self._warm_pulse()
        await self.csr_read("RESET_CTRL_AFTER_WARM", RESET_CTRL, length=8, expected=held_cores)
        post = await self._readback("WARM", self.released_ps)
        cocotb.log.info("%s PASS: %s; %s; after the release %s", CHK_WARM, pre, pulse, post)
        self.passes.append(CHK_WARM)

        await self.csr_write("CORES_RELEASE", RESET_CTRL, ctrl, length=8)
        await self._await_level(
            dut.tb_cpu_core_resets_n, "tb_cpu_core_resets_n", CORE_LEVEL_N, _LEVEL_BOUND
        )
        await self.csr_write("TIMEOUT_RESTORE", RESET_TIMEOUT, timeout, length=8)
        await self.csr_read("TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout)
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE, expected=REGION_SIZE_RESET)
